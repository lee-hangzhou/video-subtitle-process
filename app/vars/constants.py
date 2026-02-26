from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent

VIDEO_FORMATS = frozenset({".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv"})
AUDIO_FORMATS = frozenset({".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"})
SUBTITLE_FORMATS = frozenset({".srt", ".ass", ".vtt"})
IMAGE_FORMATS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".gif"})

ALI_CLOUD_VIDEO_FORMATS = frozenset({".mp4", ".mov", ".webm"})
HARDCODE_VIDEO_FORMATS = frozenset({".mp4", ".avi", ".mkv", ".mov"})
ALLOWED_SUBTITLE_FORMATS = frozenset({".srt", ".ass"})

OCR_DEFAULT_LANGUAGE = "ch"

# 水印检测：返回最有可能的水印区域数量
WATERMARK_AREA_NUM = 5

# 字幕区域偏移量（像素）
SUBTITLE_AREA_DEVIATION_PIXEL = 50

# 坐标容忍偏差（像素）
PIXEL_TOLERANCE_Y = 50
PIXEL_TOLERANCE_X = 100
OCR_DEFAULT_DROP_SCORE = 0.75
OCR_DEFAULT_SIMILARITY_THRESHOLD = 0.8
OCR_DEFAULT_EXTRACT_FREQUENCY = 3

# 坐标归一化聚类参数
COORD_CLUSTER_EPS_MIN = 0.005  # 最小eps（归一化后0.5%）
COORD_CLUSTER_EPS_MAX = 0.05  # 最大eps（归一化后5%）
COORD_CLUSTER_MIN_SAMPLES = 2  # 最小样本数
COORD_CLUSTER_EPS_X_WEIGHT = 2  # x方向eps权重
COORD_CLUSTER_EPS_Y_WEIGHT = 1  # y方向eps权重
COORD_CLUSTER_NOISE_MERGE_RATIO = 2.0  # 噪声点合并阈值（eps的倍数）

# 水印过滤参数
WATERMARK_AREA_TOP_RATIO = 0.1  # 顶部区域比例（10%）
WATERMARK_AREA_BOTTOM_RATIO = 0.9  # 底部区域比例（90%）
WATERMARK_AREA_EDGE_TOP_RATIO = 0.05  # 顶部边缘比例（5%）
WATERMARK_AREA_EDGE_BOTTOM_RATIO = 0.95  # 底部边缘比例（95%）
WATERMARK_FRAME_RATIO_THRESHOLD = 0.9  # 水印帧数占比阈值（90%）
WATERMARK_SIZE_RATIO_THRESHOLD = 0.02  # 水印尺寸阈值（归一化后2%）
WATERMARK_INTERSECTION_AREA_RATIO = 0.1  # 水印交集面积阈值（bbox面积的10%）

# 场景文字过滤参数（DBSCAN聚类）
# 特征：[y_min, x_center, h]（归一化坐标，值域0~1）
# 权重：y_min(0.5), x_center(0.2), h(0.3)
# eps基于特征的MAD动态计算，限制在[EPS_MIN, EPS_MAX]范围内
#
# 特征设计依据：
# - 主字幕：y_min≈0.7(底部), x_center≈0.5(居中), h≈0.035(小高度)
# - 画面字幕：y_min≈0.1(顶部), x_center≈0.8(偏侧), h≈0.2(大高度)
# - 主字幕vs画面字幕加权距离约0.35，多行字幕间加权距离约0.02
SCENE_TEXT_EPS_MIN = 0.03  # 最小eps（保证多行字幕能聚在一起）
SCENE_TEXT_EPS_MAX = 0.15  # 最大eps（保证主字幕和画面字幕能分开）
SCENE_TEXT_MIN_SAMPLES = 2  # 最小样本数（至少2个不同帧的bbox才能形成簇）

ASPECT_RATIO_MIN_HEIGHT = 1e-6  # 最小高度（避免除0）

ASR_DEFAULT_MODEL = "medium"
ASR_DEFAULT_LANGUAGE = "zh"
ASR_AUDIO_SAMPLE_RATE = 16000

SUBTITLE_MIN_DURATION = 1.0

MAX_WORKERS = 5
MAX_RETRIES = 3
CHUNK_SIZE = 1024 * 1024

QUVIDEO_BASE_URL = "https://api.fireflyfusion.cn/api/rest/fs/common/api"
