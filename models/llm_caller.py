# -*- coding: utf-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2024-2024. All rights reserved.
import json

import requests
import urllib3

from logger import logger
from project_configs.node_configs import DEFAULT_USER_ID
from project_configs.settings import HeaderConfig, LLMConfig
from utils.decrypt import kms_decrypt


class LLMCaller:
    """
    大模型连接类，配置请求的模型名称、用户、场景，从而请求相应模型，并返回结果
    """
    model_map = {
        "qwen2_72b": "c0eebce6-ec00-4d8e-9f61-33a75005840b",
        "llama3_70b": "1703a197-a8bd-4e28-91a5-68161e7f1a70",
        "qwen2.5_72b": "131c5e0b-a01f-47ff-9116-5e3346266112",
        "deepseek-v3": "5c87e273-728a-4b76-917d-acc61295f6ce",
        "deepseek-r1": "1d0c6b56-0630-407e-8df5-9d5076e30551",
        "r1_distill_qwen_32b": "197a9109-c53d-4301-b675-956b5fa9ac09",
        "qwen2_npu": "7bfff11c-6094-4fe1-bcb8-3f292cfd591f",
        "qwen25_for_deepwiki": "1138a73b-5049-4191-860c-51e4f0767973",
        "qwen2.5_1.5b": "48dff97a-b8ad-45e9-9deb-32d37c2b2704",
        "qwen2.5_7b": "295ebede-3a19-49fa-be1e-610e3408f497",
        "qwen2.5_32b": "7af95730-e540-4c84-9286-923f7b537f3c",
        "qwen3-32B": "7bc9daa5-831b-46ba-b4ed-0fcc769fafd7",
        "minimax-2.5-fix": "a9dc5db2-e625-487c-95a6-69c2be0831ca",
        "fuyao-DeepSeekV4-PD": "fuyao-DeepSeekV4-PD",
        "GLM-4.7": "d5926ed9-70d8-4243-a331-53cda64c7c03",
    }

    def __init__(
            self,
            *,
            model_name: str = "fuyao-DeepSeekV4-PD",
            scene: str,
    ) -> None:
        self.header = {
            "X-HW-ID": HeaderConfig.X_HW_ID,
            "X-HW-APPKEY": kms_decrypt(HeaderConfig.X_HW_APPKEY)
        }
        self.model_name = model_name
        self.user_id = kms_decrypt(DEFAULT_USER_ID)
        self.scene = scene

    def model_call(self, prompt, user_id: str = None, *, timeout=300, max_output_tokens=10240):
        """This is the custom llm."""
        http = urllib3.PoolManager(cert_reqs='CERT_NONE')
        requests_ = {
            "modelParams": {
                "stream": False,
                "prompt": prompt,
            },
            "passthroughParams": {"model_params": {"max_tokens": max_output_tokens}},
            "modelId": self.model_map.get(self.model_name),
            "userId": user_id if user_id else self.user_id,
            "appId": HeaderConfig.X_HW_ID,
            "scene": self.scene
        }

        response = None
        try:
            response = requests.post(LLMConfig.MODEL_GATE_URL, headers=self.header, json=requests_, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            message = payload.get("Message")
            if payload.get("Status") != "Success" or not isinstance(message, str) or not message.strip():
                raise ValueError("模型响应中没有有效 Message")
            return message
        except Exception as e:
            status = getattr(response, "status_code", None)
            content_type = response.headers.get("Content-Type") if response is not None else None
            response_length = len(response.content) if response is not None else 0
            logger.error(
                "请求大模型出错: type=%s status=%s content_type=%s response_length=%s",
                type(e).__name__, status, content_type, response_length
            )
            return ""
