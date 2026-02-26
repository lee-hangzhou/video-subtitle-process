import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict
from typing import Any

import httpx

from app.core import settings
from app.core.quvideo.schema import SubtitleEraseRequest, SubtitleEraseResponse, TaskResultResponse
from app.vars.constants import QUVIDEO_BASE_URL


class QuVideo:
    def __init__(self):
        self.ak = settings.quvideo.ak
        self.sk = settings.quvideo.sk
        self.base_url = QUVIDEO_BASE_URL

    async def erase_subtitle(self, request: SubtitleEraseRequest) -> SubtitleEraseResponse:
        params = request.model_dump(by_alias=True, exclude_none=True)
        return await self._post("/subtitle/erase", params, SubtitleEraseResponse)

    async def get_task_result(self, business_id: str) -> TaskResultResponse:
        params = {"businessId": business_id}
        return await self._get("/task/result", params, TaskResultResponse)

    async def _get(self, path: str, params: dict[str, Any], response_model: type) -> Any:
        url = f"{self.base_url}{path}"
        authorization = self._generate_authorization(params)
        headers = {"Authorization": authorization}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        result = response_model(**response.json())

        if not result.success:
            raise RuntimeError(f"API error [{result.code}]: {result.message}")

        return result

    async def _post(self, path: str, params: dict[str, Any], response_model: type) -> Any:
        url = f"{self.base_url}{path}"
        authorization = self._generate_authorization(params)
        headers = {
            "Content-Type": "application/json",
            "Authorization": authorization,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, content=json.dumps(params), headers=headers)
        response.raise_for_status()
        result = response_model(**response.json())

        if not result.success:
            raise RuntimeError(f"API error [{result.code}]: {result.message}")

        return result

    def _generate_authorization(self, args: dict[str, Any]) -> str:
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(8)
        params = OrderedDict(**args)

        sign_param_map = self._build_sign_param_map(params, timestamp, nonce)
        raw_str = self._concatenate_values(sign_param_map)
        sign_str = self._get_hmac_sha256_hash(raw_str)
        raw_authorization = self._build_authorization(timestamp, nonce, sign_str)

        return base64.b64encode(raw_authorization.encode()).decode()

    def _build_sign_param_map(
            self,
            param_map: dict[str, Any],
            timestamp: str,
            nonce: str,
    ) -> OrderedDict[str, Any]:
        sign_param_map = OrderedDict()
        sign_param_map.update(param_map)
        sign_param_map["accessKey"] = self.ak
        sign_param_map["timestamp"] = timestamp
        sign_param_map["nonce"] = nonce
        sign_param_map["secretKey"] = self.sk
        return sign_param_map

    def _build_authorization(self, timestamp: str, nonce: str, sign: str) -> str:
        return self.ak + "." + sign + "." + timestamp + "." + nonce

    def _get_hmac_sha256_hash(self, raw_str: str) -> str:
        hmac_sha256 = hmac.new(self.sk.encode(), raw_str.encode(), hashlib.sha256)
        return hmac_sha256.hexdigest()

    def _concatenate_values(self, param_map: dict[str, Any]) -> str:
        result = ""
        for key in sorted(param_map.keys()):
            value = param_map[key]
            if value is not None:
                result += self._concatenate_value(value)
        return result

    def _concatenate_value(self, value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, (int, float, str)):
            return str(value)

        if isinstance(value, (list, tuple)):
            result = ""
            for item in value:
                result += self._concatenate_value(item)
            return result

        if isinstance(value, dict):
            return self._concatenate_values(value)

        if isinstance(value, object):
            properties_map = self._get_all_properties(value)
            return self._concatenate_values(properties_map)

        return ""

    def _get_all_properties(self, obj: Any) -> OrderedDict[str, Any]:
        properties_map = OrderedDict()
        for attr, value in obj.__dict__.items():
            if value is not None:
                if isinstance(value, (int, float, str)):
                    properties_map[attr] = value
                elif isinstance(value, (list, tuple, dict)):
                    properties_map[attr] = value
                elif isinstance(value, object):
                    properties_map[attr] = self._get_all_properties(value)
        return properties_map


quvideo = QuVideo()
