import os
import queue
import subprocess
from collections import defaultdict
from threading import Thread
from typing import Optional, Tuple

import cv2
import numpy as np
from Levenshtein import ratio
from paddleocr import PaddleOCR
from shapely.geometry import Polygon
from sklearn.cluster import DBSCAN
from tqdm import tqdm

from app.core import logger
from app.schemas.subtitle_extract import OCRConfig, ExtractMode, SubtitleArea, RawSubtitle, SubtitleSegment
from app.utils.str import write_srt
from app.vars.constants import VIDEO_FORMATS, PIXEL_TOLERANCE_X, PIXEL_TOLERANCE_Y, COORD_CLUSTER_EPS_Y_WEIGHT, \
    COORD_CLUSTER_EPS_X_WEIGHT, COORD_CLUSTER_EPS_MAX, COORD_CLUSTER_EPS_MIN, COORD_CLUSTER_MIN_SAMPLES, \
    COORD_CLUSTER_NOISE_MERGE_RATIO, WATERMARK_AREA_TOP_RATIO, WATERMARK_AREA_BOTTOM_RATIO, \
    WATERMARK_AREA_EDGE_TOP_RATIO, WATERMARK_AREA_EDGE_BOTTOM_RATIO, WATERMARK_INTERSECTION_AREA_RATIO, \
    WATERMARK_SIZE_RATIO_THRESHOLD, WATERMARK_FRAME_RATIO_THRESHOLD, SCENE_TEXT_MIN_SAMPLES, SCENE_TEXT_EPS_MIN, \
    SCENE_TEXT_EPS_MAX, SUBTITLE_MIN_DURATION

# 禁用 oneDNN，避免 Windows 上 OneDnnContext/fused_conv2d 报错
os.environ["FLAGS_use_mkldnn"] = "0"




class OCRExtractor:

    def __init__(self, config: Optional[OCRConfig] = None):
        self.config = config or OCRConfig()
        self._ocr = None
        self._detector = None

    @property
    def detector(self) -> PaddleOCR:
        """轻量检测器，只检测不识别"""
        if self._detector is None:
            self._detector = PaddleOCR(
                use_angle_cls=False,
                lang=self.config.language,
                use_gpu=self.config.use_gpu,
                show_log=False,
                rec=False,
            )
        return self._detector

    @property
    def ocr(self) -> PaddleOCR:
        if self._ocr is None:
            self._ocr = PaddleOCR(
                use_angle_cls=False,
                lang=self.config.language,
                use_gpu=self.config.use_gpu,
                show_log=False,
                drop_score=0,  # 不在这里过滤，后处理时过滤
                rec_batch_num=6,
                max_batch_size=10,
            )
        return self._ocr

    def extract(
            self,
            video_path: str,
            output_path: Optional[str] = None,
    ) -> str:
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        ext = os.path.splitext(video_path)[1].lower()
        if ext not in VIDEO_FORMATS:
            raise ValueError(f"Unsupported video format: {ext}")

        if output_path is None:
            output_path = os.path.splitext(video_path)[0] + "_ocr.srt"

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # 获取视频信息
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        subtitle_area = self.config.subtitle_area
        raw_subtitles = []

        total_sampled_frames = 0
        frame_queue = queue.Queue(maxsize=50)

        def consumer():
            nonlocal total_sampled_frames
            while True:
                item = frame_queue.get()
                if item is None:
                    break
                frame_no, frame = item
                total_sampled_frames += 1  # 统计抽帧总数
                results = self._ocr_frame(frame, subtitle_area)
                for r in results:
                    raw_subtitles.append(RawSubtitle(frame_no=frame_no, **r))

        consumer_thread = Thread(target=consumer, daemon=True)
        consumer_thread.start()

        if self.config.extract_mode == ExtractMode.FPS:
            self._extract_by_fps(video_path, frame_queue, fps, frame_count)
        else:
            self._extract_by_detect(video_path, frame_queue, frame_count)

        frame_queue.put(None)
        consumer_thread.join()

        logger.info(f"OCR识别结果数量: {len(raw_subtitles)}")

        # 坐标归一化，统一相近坐标便于后续过滤统计
        raw_subtitles = self._unite_coordinates(raw_subtitles, frame_width, frame_height)
        logger.info(f"坐标归一化后数量: {len(raw_subtitles)}")

        # 水印过滤，先于场景文字过滤，避免水印被选为主字幕簇
        if self.config.filter_watermark:
            before_count = len(raw_subtitles)
            raw_subtitles = self._filter_watermark(
                raw_subtitles, frame_width, frame_height, total_sampled_frames
            )
            logger.info(f"水印过滤: {before_count} -> {len(raw_subtitles)}")

        # 场景文字过滤，在水印过滤之后，选择最大簇作为字幕
        if self.config.filter_scene_text:
            before_count = len(raw_subtitles)
            filtered_subtitles = self._filter_scene_text(
                raw_subtitles, frame_width, frame_height, total_sampled_frames
            )
            logger.info(f"场景文字过滤: {before_count} -> {len(filtered_subtitles)}")

            if len(filtered_subtitles) == 0 and before_count > 0:
                logger.warning("场景文字过滤后结果为空，保留原始结果")
            else:
                raw_subtitles = filtered_subtitles

        # 检测视频帧率类型
        is_cfr = self._is_constant_frame_rate(video_path)

        # 后处理
        segments = self._post_process(raw_subtitles, fps, video_path, is_cfr)
        write_srt(segments, output_path)

        return output_path

    def _extract_by_fps(
            self,
            video_path: str,
            frame_queue: queue.Queue,
            fps: float,
            frame_count: int,
    ) -> None:
        cap = cv2.VideoCapture(video_path)
        try:
            frame_interval = max(1, int(fps / self.config.extract_frequency))
            total_frames = int(frame_count / frame_interval)

            with tqdm(total=total_frames, desc="OCR 提取", unit="帧") as pbar:
                current_frame = 0
                while current_frame < frame_count:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
                    ret, frame = cap.read()
                    if not ret:
                        break

                    frame_queue.put((current_frame, frame))
                    pbar.update(1)
                    current_frame += frame_interval
        finally:
            cap.release()

    def _extract_by_detect(
            self,
            video_path: str,
            frame_queue: queue.Queue,
            frame_count: int,
    ) -> None:
        """DETECT模式,检测到字幕变化时才做OCR"""
        cap = cv2.VideoCapture(video_path)
        try:
            prev_boxes = None

            with tqdm(total=frame_count, desc="OCR 提取(DETECT)", unit="帧") as pbar:
                frame_no = 0
                while frame_no < frame_count:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
                    ret, frame = cap.read()
                    if not ret:
                        break

                    curr_boxes = self._detect_boxes(frame)

                    if self._boxes_changed(prev_boxes, curr_boxes):
                        frame_queue.put((frame_no, frame))

                    prev_boxes = curr_boxes
                    pbar.update(1)
                    frame_no += 1
        finally:
            cap.release()

    @staticmethod
    def _extract_bbox_coords(box: list) -> tuple[int, int, int, int]:
        """从OCR检测框坐标中提取边界框坐标 (xmin, xmax, ymin, ymax)"""
        x_coords = [p[0] for p in box]
        y_coords = [p[1] for p in box]
        xmin, xmax = int(min(x_coords)), int(max(x_coords))
        ymin, ymax = int(min(y_coords)), int(max(y_coords))
        return xmin, xmax, ymin, ymax

    def _detect_boxes(self, frame) -> list[tuple]:
        """轻量检测，只返回检测框坐标"""
        result = self.detector.ocr(frame, rec=False)
        if not result or not result[0]:
            return []

        boxes = []
        for box in result[0]:
            xmin, xmax, ymin, ymax = self._extract_bbox_coords(box)
            # 对齐到 10 像素，减少抖动
            ymin = self._round_to_10(ymin)
            boxes.append((xmin, xmax, ymin, ymax))
        return sorted(boxes, key=lambda b: (b[2], b[0]))

    @staticmethod
    def _boxes_changed(
            prev_boxes: Optional[list[tuple]],
            curr_boxes: list[tuple],
    ) -> bool:
        """判断检测框是否有变化"""
        if prev_boxes is None:
            return len(curr_boxes) > 0

        if len(prev_boxes) != len(curr_boxes):
            return True

        for prev, curr in zip(prev_boxes, curr_boxes):
            px1, px2, py1, py2 = prev
            cx1, cx2, cy1, cy2 = curr
            if (abs(px1 - cx1) > PIXEL_TOLERANCE_X or
                    abs(px2 - cx2) > PIXEL_TOLERANCE_X or
                    abs(py1 - cy1) > PIXEL_TOLERANCE_Y or
                    abs(py2 - cy2) > PIXEL_TOLERANCE_Y):
                return True

        return False

    def _ocr_frame(
            self,
            frame,
            subtitle_area: Optional[SubtitleArea],
    ) -> list[dict]:
        result = self.ocr.ocr(frame, cls=False)
        if not result or not result[0]:
            return []

        # 如果指定了字幕区域，构建 polygon 用于过滤
        area_polygon = None
        if subtitle_area is not None:
            area_polygon = Polygon([
                [subtitle_area.x_min, subtitle_area.y_min],
                [subtitle_area.x_max, subtitle_area.y_min],
                [subtitle_area.x_max, subtitle_area.y_max],
                [subtitle_area.x_min, subtitle_area.y_max],
            ])

        texts = []
        for line in result[0]:
            box, (text, confidence) = line[0], line[1]
            if confidence < self.config.drop_score:
                continue

            xmin, xmax, ymin, ymax = self._extract_bbox_coords(box)

            # 如果指定了字幕区域，过滤不在区域内的结果
            if area_polygon is not None:
                text_polygon = Polygon([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]])
                intersection = area_polygon.intersection(text_polygon)

                if intersection.is_empty:
                    continue

                # 越界检查
                overflow_rate = (area_polygon.area + text_polygon.area - intersection.area) / area_polygon.area - 1
                if overflow_rate > self.config.area_deviation_rate:
                    continue

            ymin_aligned = self._round_to_10(ymin)

            texts.append({
                "x_min": xmin,
                "x_max": xmax,
                "y_min": ymin_aligned,
                "y_max": ymax,
                "text": text,
                "confidence": confidence,
            })

        texts.sort(key=lambda t: (t["y_min"], t["x_min"]))
        return texts

    @staticmethod
    def _round_to_10(y: int) -> int:
        y_up = y + 10 - y % 10
        y_down = y - y % 10
        return y_up if abs(y - y_up) < abs(y - y_down) else y_down

    @staticmethod
    def _unite_coordinates(
            raw_subtitles: list[RawSubtitle],
            frame_width: int,
            frame_height: int
    ) -> list[RawSubtitle]:
        """
        坐标归一化：将相近的bbox坐标归并为统一值，减少帧间抖动
        使用DBSCAN聚类，eps基于像素容忍度动态计算以适配不同分辨率
        """
        if not raw_subtitles:
            return raw_subtitles

        # 提取归一化特征
        features = []
        subtitle_list = []  # 保存特征对应的原始字幕对象
        for sub in raw_subtitles:
            x_min_norm = sub.x_min / frame_width
            x_max_norm = sub.x_max / frame_width
            y_min_norm = sub.y_min / frame_height
            y_max_norm = sub.y_max / frame_height

            feature = np.array([x_min_norm, x_max_norm, y_min_norm, y_max_norm])
            features.append(feature)
            subtitle_list.append(sub)

        features = np.array(features)

        # 动态计算eps,基于原像素容忍度，转换为归一化值
        eps_x = PIXEL_TOLERANCE_X / frame_width
        eps_y = PIXEL_TOLERANCE_Y / frame_height
        total_weight = COORD_CLUSTER_EPS_X_WEIGHT + COORD_CLUSTER_EPS_Y_WEIGHT
        eps = (eps_x * COORD_CLUSTER_EPS_X_WEIGHT + eps_y * COORD_CLUSTER_EPS_Y_WEIGHT) / total_weight
        eps = max(COORD_CLUSTER_EPS_MIN, min(COORD_CLUSTER_EPS_MAX, eps))

        clustering = DBSCAN(
            eps=eps,
            min_samples=COORD_CLUSTER_MIN_SAMPLES,
            metric='manhattan',
            n_jobs=-1
        )
        cluster_labels = clustering.fit_predict(features)

        # 计算每个簇的平均坐标,作为归一化坐标
        # 先处理非噪声点，构建初始簇
        cluster_dict = defaultdict(list)
        noise_indices = []
        for idx, label in enumerate(cluster_labels):
            if label == -1:
                noise_indices.append(idx)
            else:
                cluster_dict[label].append(subtitle_list[idx])

        # 对噪声点进行二次聚类：尝试与已有簇合并
        for noise_idx in noise_indices:
            noise_feature = features[noise_idx]
            merged = False
            # 如果距离足够近,尝试与已有簇合并
            for existing_label, existing_subs in cluster_dict.items():
                if isinstance(existing_label, int):  # 跳过已合并的噪声点
                    # 计算与簇中心的距离
                    existing_feature = features[existing_subs[0] if existing_subs else noise_idx]
                    distance = np.sum(np.abs(noise_feature - existing_feature))
                    if distance < eps * COORD_CLUSTER_NOISE_MERGE_RATIO:
                        cluster_dict[existing_label].append(subtitle_list[noise_idx])
                        merged = True
                        break
            if not merged:
                # 无法合并，单独成簇
                cluster_dict[f"noise_{noise_idx}"].append(subtitle_list[noise_idx])

        unified_subs = []
        for cluster_key, subs in cluster_dict.items():
            # 计算簇内坐标的均值
            x_mins = [s.x_min for s in subs]
            x_maxs = [s.x_max for s in subs]
            y_mins = [s.y_min for s in subs]
            y_maxs = [s.y_max for s in subs]

            avg_xmin = int(np.round(np.mean(x_mins)))
            avg_xmax = int(np.round(np.mean(x_maxs)))
            avg_ymin = int(np.round(np.mean(y_mins)))
            avg_ymax = int(np.round(np.mean(y_maxs)))

            # 更新坐标
            for sub in subs:
                unified_subs.append(RawSubtitle(
                    frame_no=sub.frame_no,
                    x_min=avg_xmin,
                    x_max=avg_xmax,
                    y_min=avg_ymin,
                    y_max=avg_ymax,
                    text=sub.text,
                    confidence=sub.confidence,
                ))

        return unified_subs

    @staticmethod
    def _filter_watermark(
            raw_subtitles: list[RawSubtitle],
            frame_width: int,
            frame_height: int,
            total_sampled_frames: int
    ) -> list[RawSubtitle]:
        """
        水印过滤：结合位置+频率+文本+尺寸特征
        """
        if not raw_subtitles or total_sampled_frames == 0:
            return raw_subtitles

        # 预定义水印高危区域
        watermark_polygons = [
            # 左上：x<10%, y<10%
            Polygon([
                (0, 0),
                (WATERMARK_AREA_TOP_RATIO * frame_width, 0),
                (WATERMARK_AREA_TOP_RATIO * frame_width, WATERMARK_AREA_TOP_RATIO * frame_height),
                (0, WATERMARK_AREA_TOP_RATIO * frame_height)
            ]),
            # 右上：x>90%, y<10%
            Polygon([
                (WATERMARK_AREA_BOTTOM_RATIO * frame_width, 0),
                (frame_width, 0),
                (frame_width, WATERMARK_AREA_TOP_RATIO * frame_height),
                (WATERMARK_AREA_BOTTOM_RATIO * frame_width, WATERMARK_AREA_TOP_RATIO * frame_height)
            ]),
            # 左下：x<10%, y>90%
            Polygon([
                (0, WATERMARK_AREA_BOTTOM_RATIO * frame_height),
                (WATERMARK_AREA_TOP_RATIO * frame_width, WATERMARK_AREA_BOTTOM_RATIO * frame_height),
                (WATERMARK_AREA_TOP_RATIO * frame_width, frame_height),
                (0, frame_height)
            ]),
            # 右下：x>90%, y>90%
            Polygon([
                (WATERMARK_AREA_BOTTOM_RATIO * frame_width, WATERMARK_AREA_BOTTOM_RATIO * frame_height),
                (frame_width, WATERMARK_AREA_BOTTOM_RATIO * frame_height),
                (frame_width, frame_height),
                (WATERMARK_AREA_BOTTOM_RATIO * frame_width, frame_height)
            ]),
            # 顶部边缘：y<5%
            Polygon([
                (0, 0),
                (frame_width, 0),
                (frame_width, WATERMARK_AREA_EDGE_TOP_RATIO * frame_height),
                (0, WATERMARK_AREA_EDGE_TOP_RATIO * frame_height)
            ]),
            # 底部边缘：y>95%
            Polygon([
                (0, WATERMARK_AREA_EDGE_BOTTOM_RATIO * frame_height),
                (frame_width, WATERMARK_AREA_EDGE_BOTTOM_RATIO * frame_height),
                (frame_width, frame_height),
                (0, frame_height)
            ])
        ]

        coord_to_subs = defaultdict(list)
        coord_to_frames = defaultdict(set)
        for sub in raw_subtitles:
            coord = (sub.x_min, sub.x_max, sub.y_min, sub.y_max)
            coord_to_subs[coord].append(sub)
            coord_to_frames[coord].add(sub.frame_no)

        watermark_coords = set()
        for coord, subs in coord_to_subs.items():
            x_min, x_max, y_min, y_max = coord
            # 构建当前bbox的Polygon
            bbox_polygon = Polygon([
                (x_min, y_min), (x_max, y_min),
                (x_max, y_max), (x_min, y_max)
            ])

            # 位置判断：bbox与水印区域是否有交集
            bbox_area = bbox_polygon.area
            in_watermark_area = False
            for wp in watermark_polygons:
                intersection = bbox_polygon.intersection(wp)
                # 交集面积必须大于bbox面积的阈值，避免误判
                if intersection.area > bbox_area * WATERMARK_INTERSECTION_AREA_RATIO:
                    in_watermark_area = True
                    break

            frame_count = len(coord_to_frames[coord])
            frame_ratio = frame_count / total_sampled_frames

            # 文本判断：同一coord的文本是否固定
            texts = {s.text.strip() for s in subs}
            text_fixed = len(texts) == 1

            bbox_w = x_max - x_min
            bbox_h = y_max - y_min
            is_small = (bbox_w / frame_width < WATERMARK_SIZE_RATIO_THRESHOLD) or (
                    bbox_h / frame_height < WATERMARK_SIZE_RATIO_THRESHOLD)

            # 满足任一条件则判定为水印
            # 1. 在水印高危区域
            # 2. 不在高危区域，但满足频率和文本条件
            # 3. 尺寸太小
            if in_watermark_area or (
                    not in_watermark_area and frame_ratio > WATERMARK_FRAME_RATIO_THRESHOLD and text_fixed) or is_small:
                watermark_coords.add(coord)

        return [
            sub for sub in raw_subtitles
            if (sub.x_min, sub.x_max, sub.y_min, sub.y_max) not in watermark_coords
        ]

    @staticmethod
    def _extract_subtitle_features(
            raw_subtitles: list[RawSubtitle],
            frame_width: int,
            frame_height: int,
    ) -> Tuple[np.ndarray, list[dict]]:
        """
        提取字幕特征向量

        特征设计基于字幕的物理位置特性：
        - y_min: 主字幕在底部(≈0.7)，画面字幕在顶部(≈0.05~0.2)，差异显著
        - x_center: 主字幕居中(≈0.5)，画面字幕偏侧(≈0.8~0.9)
        - h: 主字幕高度小(≈0.035)，画面字幕高度大(≈0.13~0.22)
        """
        feature_list = []
        bbox_info_list = []

        for sub in raw_subtitles:
            # 归一化坐标,值域0~1
            x_center = (sub.x_min + sub.x_max) / 2.0 / frame_width
            y_min = sub.y_min / frame_height
            h = (sub.y_max - sub.y_min) / frame_height

            feature = np.array([
                y_min,
                x_center,
                h
            ])
            feature_list.append(feature)
            bbox_info_list.append({
                "sub": sub,
                "x_center": x_center,
                "y_min": y_min,
                "h": h,
            })

        return np.array(feature_list), bbox_info_list

    @staticmethod
    def _weighted_manhattan_distance(a: np.ndarray, b: np.ndarray) -> float:
        """
        自定义加权曼哈顿距离
        特征顺序：[y_min, x_center, h]
        权重：y_min(0.5)、x_center(0.2)、h(0.3)
        """
        if len(a) != 3 or len(b) != 3:
            return float(np.sum(np.abs(a - b)))  # 降级为普通曼哈顿距离

        # 按权重计算距离
        y_min_diff = abs(a[0] - b[0]) * 0.5
        x_center_diff = abs(a[1] - b[1]) * 0.2
        h_diff = abs(a[2] - b[2]) * 0.3
        total_diff = y_min_diff + x_center_diff + h_diff

        return float(total_diff)

    @staticmethod
    def _calculate_dbscan_params(
            frame_height: int,
            feature_array: np.ndarray,
    ) -> Tuple[float, int]:
        """
        动态计算DBSCAN参数eps：基于特征分布的中位数绝对偏差
        """
        min_samples = max(SCENE_TEXT_MIN_SAMPLES, 2)

        # 动态计算eps,基于特征的MAD
        if len(feature_array) < min_samples:
            eps = SCENE_TEXT_EPS_MIN
        else:
            # 计算每个特征维度的MAD
            medians = np.median(feature_array, axis=0)
            mad = np.median(np.abs(feature_array - medians), axis=0)
            weighted_mad = (mad[0] * 0.5 + mad[1] * 0.2 + mad[2] * 0.3) * 1.5
            # 钳位到合理范围，避免极端值
            eps = max(SCENE_TEXT_EPS_MIN, min(SCENE_TEXT_EPS_MAX, weighted_mad))

        logger.debug(f"动态DBSCAN参数: eps={eps:.6f}, min_samples={min_samples}")
        return eps, min_samples

    @staticmethod
    def _perform_dbscan_clustering(
            feature_array: np.ndarray,
            eps: float,
            min_samples: int,
    ) -> Tuple[np.ndarray, int, int]:
        """
        执行DBSCAN聚类
        """
        if len(feature_array) == 0:
            return np.array([]), 0, 0

        # 计算加权曼哈顿距离矩阵
        n = len(feature_array)
        dist_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                dist = OCRExtractor._weighted_manhattan_distance(feature_array[i], feature_array[j])
                dist_matrix[i][j] = dist
                dist_matrix[j][i] = dist

        clustering = DBSCAN(
            eps=eps,
            min_samples=min_samples,
            metric="precomputed",
            n_jobs=-1
        )
        cluster_labels = clustering.fit_predict(dist_matrix)

        unique_labels = set(cluster_labels)
        noise_count = list(cluster_labels).count(-1)
        cluster_count = len(unique_labels) - (1 if -1 in unique_labels else 0)

        # 加权距离统计,调试
        distances = dist_matrix[np.triu_indices(n, k=1)]
        if len(distances) > 0:
            min_dist = np.min(distances)
            max_dist = np.max(distances)
            mean_dist = np.mean(distances)
            median_dist = np.median(distances)
            logger.debug(
                f"DBSCAN聚类结果: 簇数={cluster_count}, 噪声点={noise_count}, eps={eps:.6f}, min_samples={min_samples}")
            logger.debug(
                f"加权距离统计: 最小={min_dist:.6f}, 最大={max_dist:.6f}, 平均={mean_dist:.6f}, 中位数={median_dist:.6f}")
        else:
            logger.debug(
                f"DBSCAN聚类结果: 簇数={cluster_count}, 噪声点={noise_count}, eps={eps:.6f}, min_samples={min_samples}")

        return cluster_labels, cluster_count, noise_count

    @staticmethod
    def _build_cluster_info(
            cluster_labels: np.ndarray,
            bbox_info_list: list[dict],
    ) -> Tuple[defaultdict, set]:
        """
        构建簇信息和噪声点文本
        """
        cluster_info = defaultdict(lambda: {
            "frames": set(),
            "x_centers": [],
            "y_mins": [],
            "heights": [],
            "subs": []
        })
        noise_texts = set()

        for idx, label in enumerate(cluster_labels):
            bbox_info = bbox_info_list[idx]
            sub = bbox_info["sub"]

            if label == -1:
                noise_texts.add(sub.text.strip())
                continue

            cluster_info[label]["frames"].add(sub.frame_no)
            cluster_info[label]["x_centers"].append(bbox_info["x_center"])
            cluster_info[label]["y_mins"].append(bbox_info["y_min"])
            cluster_info[label]["heights"].append(bbox_info["h"])
            cluster_info[label]["subs"].append(sub)

        return cluster_info, noise_texts

    @staticmethod
    def _merge_similar_clusters(cluster_info: defaultdict, eps: float) -> defaultdict:
        """
        合并特征相似的簇
        """
        if len(cluster_info) <= 1:
            return cluster_info

        cluster_means = {
            label: np.array(OCRExtractor._get_cluster_feature_mean(info))
            for label, info in cluster_info.items()
        }

        # 合并距离<eps的簇
        merged_clusters = defaultdict(list)
        visited = set()

        for label1 in cluster_info.keys():
            if label1 in visited:
                continue
            merged_clusters[label1].append(label1)
            visited.add(label1)

            for label2 in cluster_info.keys():
                if label2 in visited or label1 == label2:
                    continue
                # 计算簇间加权距离
                dist = OCRExtractor._weighted_manhattan_distance(cluster_means[label1], cluster_means[label2])
                if dist < eps:
                    merged_clusters[label1].append(label2)
                    visited.add(label2)

        new_cluster_info = defaultdict(lambda: {
            "frames": set(),
            "x_centers": [],
            "y_mins": [],
            "heights": [],
            "subs": []
        })
        for new_label, old_labels in merged_clusters.items():
            for old_label in old_labels:
                info = cluster_info[old_label]
                new_cluster_info[new_label]["frames"].update(info["frames"])
                new_cluster_info[new_label]["x_centers"].extend(info["x_centers"])
                new_cluster_info[new_label]["y_mins"].extend(info["y_mins"])
                new_cluster_info[new_label]["heights"].extend(info["heights"])
                new_cluster_info[new_label]["subs"].extend(info["subs"])

        return new_cluster_info

    @staticmethod
    def _select_top_clusters(
            cluster_info: defaultdict,
            top_n: int = 1
    ) -> list[Tuple[int, dict]]:
        """选择样本数最多的前N个簇"""
        if not cluster_info:
            return []
        sorted_clusters = sorted(
            cluster_info.items(),
            key=lambda x: len(x[1]["subs"]),
            reverse=True
        )
        return sorted_clusters[:top_n]

    @staticmethod
    def _get_cluster_feature_mean(info: dict) -> Tuple[float, float, float]:
        """获取簇的特征均值 (y_min, x_center, h)"""
        if not info["y_mins"]:
            return 0.0, 0.0, 0.0
        return np.mean(info["y_mins"]), np.mean(info["x_centers"]), np.mean(info["heights"])

    @staticmethod
    def _log_cluster_selection(
            cluster_info: defaultdict,
            noise_texts: set,
            selected_clusters: list[Tuple[int, dict]],
            eps: float,
    ) -> None:
        total_bbox = sum(len(info["subs"]) for _, info in selected_clusters)
        selected_labels = [str(label) for label, _ in selected_clusters]

        for label, info in selected_clusters:
            texts = sorted(set(sub.text.strip() for sub in info["subs"]))
            logger.info(
                f"场景文字过滤: 选择簇={label}, 帧数={len(info['frames'])}, "
                f"bbox数={len(info['subs'])}, 文本={', '.join(texts)}"
            )

        logger.info(
            f"场景文字过滤完成: 总簇数={len(cluster_info)}, 选择簇={','.join(selected_labels)}, 保留bbox数={total_bbox}")

        if noise_texts:
            logger.debug(f"噪声点文本（{len(noise_texts)}种）: {', '.join(sorted(noise_texts))}")

        if len(cluster_info) > 1:
            logger.debug("所有簇特征分析:")
            all_clusters = [(label, info) for label, info in cluster_info.items()]
            all_clusters.sort(key=lambda x: len(x[1]["subs"]), reverse=True)

            for label, info in all_clusters:
                if not info["y_mins"]:
                    continue
                y_min_mean, x_center_mean, h_mean = OCRExtractor._get_cluster_feature_mean(info)
                texts = sorted(set(sub.text.strip() for sub in info["subs"]))
                logger.debug(
                    f"  簇 {label}: bbox数={len(info['subs'])}, 帧数={len(info['frames'])}, "
                    f"特征均值(y_min={y_min_mean:.4f}, x_center={x_center_mean:.4f}, h={h_mean:.4f}), "
                    f"文本={', '.join(texts)}"
                )

            logger.debug("前3个最大簇之间的特征距离:")
            for i in range(min(3, len(all_clusters))):
                for j in range(i + 1, min(3, len(all_clusters))):
                    label_i, info_i = all_clusters[i]
                    label_j, info_j = all_clusters[j]
                    feat_i = np.array(OCRExtractor._get_cluster_feature_mean(info_i))
                    feat_j = np.array(OCRExtractor._get_cluster_feature_mean(info_j))
                    dist = OCRExtractor._weighted_manhattan_distance(feat_i, feat_j)
                    logger.debug(f"    簇 {label_i} <-> 簇 {label_j}: 加权距离={dist:.6f}, eps={eps:.6f}")

    def _filter_scene_text(
            self,
            raw_subtitles: list[RawSubtitle],
            frame_width: int,
            frame_height: int,
            total_sampled_frames: int,
    ) -> list[RawSubtitle]:
        """
        场景文字过滤：基于DBSCAN聚类，选择样本最多的簇作为主字幕
        如果 include_secondary_subtitle=True，同时保留次大簇（副字幕）
        """
        if not raw_subtitles or total_sampled_frames == 0:
            return raw_subtitles

        feature_array, bbox_info_list = self._extract_subtitle_features(
            raw_subtitles, frame_width, frame_height
        )

        eps, min_samples = self._calculate_dbscan_params(frame_height, feature_array)

        cluster_labels, cluster_count, noise_count = self._perform_dbscan_clustering(
            feature_array, eps, min_samples
        )

        cluster_info, noise_texts = self._build_cluster_info(cluster_labels, bbox_info_list)
        cluster_info = self._merge_similar_clusters(cluster_info, eps)

        top_n = 2 if self.config.include_secondary_subtitle else 1
        selected_clusters = self._select_top_clusters(cluster_info, top_n)
        if not selected_clusters:
            logger.warning("场景文字过滤: 没有有效簇")
            return []

        valid_subs = []
        for label, info in selected_clusters:
            valid_subs.extend(info["subs"])

        self._log_cluster_selection(cluster_info, noise_texts, selected_clusters, eps)

        return valid_subs

    @staticmethod
    def _is_constant_frame_rate(video_path: str) -> bool:
        """检测视频帧率类型，True=固定帧率(CFR)，False=可变帧率(VFR)"""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate,avg_frame_rate",
                    "-of", "default=noprint_wrappers=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            if result.returncode != 0:
                logger.warning("ffprobe failed to detect frame rate")
                return True

            r_frame_rate = None
            avg_frame_rate = None
            for line in result.stdout.splitlines():
                if line.startswith("r_frame_rate="):
                    r_frame_rate = line.split("=", 1)[1].strip()
                elif line.startswith("avg_frame_rate="):
                    avg_frame_rate = line.split("=", 1)[1].strip()

            if r_frame_rate and avg_frame_rate:
                return r_frame_rate == avg_frame_rate

            logger.warning("Unable to determine frame rate")
            return True

        except subprocess.TimeoutExpired:
            logger.warning("ffprobe timeout")
            return True
        except Exception as e:
            logger.warning("Failed to detect frame rate: %s", str(e))
            return True

    def _post_process(
            self,
            raw_subtitles: list[RawSubtitle],
            fps: float,
            video_path: str,
            is_cfr: bool,
    ) -> list[SubtitleSegment]:
        if not raw_subtitles:
            return []

        frame_texts: dict[int, str] = {}
        for sub in raw_subtitles:
            if sub.frame_no in frame_texts:
                frame_texts[sub.frame_no] += " " + sub.text
            else:
                frame_texts[sub.frame_no] = sub.text

        sorted_frames = sorted(frame_texts.items())

        merged: list[tuple[int, int, str]] = []
        i = 0
        while i < len(sorted_frames):
            start_frame, text = sorted_frames[i]
            end_frame = start_frame

            j = i + 1
            while j < len(sorted_frames):
                next_frame, next_text = sorted_frames[j]
                similarity = ratio(text.replace(" ", ""), next_text.replace(" ", ""))
                if similarity >= self.config.similarity_threshold:
                    if len(next_text) > len(text):
                        text = next_text
                    end_frame = next_frame
                    j += 1
                else:
                    break

            merged.append((start_frame, end_frame, text))
            i = j

        cap = cv2.VideoCapture(video_path)
        try:
            segments = []
            for idx, (start_frame, end_frame, text) in enumerate(merged, 1):
                start_time = self._frame_to_time(cap, start_frame, fps, is_cfr)
                end_time = self._frame_to_time(cap, end_frame + 1, fps, is_cfr)

                if end_time - start_time < SUBTITLE_MIN_DURATION:
                    end_time = start_time + SUBTITLE_MIN_DURATION

                segments.append(SubtitleSegment(
                    index=idx,
                    start_time=start_time,
                    end_time=end_time,
                    text=text.strip(),
                ))

            # 由于上面+1s的逻辑，会出现字幕重叠的问题，需要检测重叠，若当前字幕的结束时间大于下一条字幕的开始时间，则需要进行扣减，避免出现重叠
            for i in range(len(segments) - 1):
                current_end = segments[i].end_time
                next_start = segments[i + 1].start_time

                if current_end > next_start:
                    # 将当前字幕的结束时间调整为下一个字幕开始时间 - 0.05秒
                    segments[i].end_time = next_start - 0.05

            return segments
        finally:
            cap.release()

    @staticmethod
    def _frame_to_time(
            cap: cv2.VideoCapture,
            frame_no: int,
            fps: float,
            is_cfr: bool,
    ) -> float:
        """将帧号转换为时间（秒），CFR直接计算，VFR从视频读取真实时间戳"""
        if is_cfr:
            return frame_no / fps
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        return ms / 1000.0 if ms > 0 else frame_no / fps
