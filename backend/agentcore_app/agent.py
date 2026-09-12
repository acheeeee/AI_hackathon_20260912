"""AgentCore Runtime 上執行的最小代理，非直接被 caseapi import。

這個檔案會被 `backend/scripts/deploy_agentcore.py` 打包成 .zip 直接部署到
AWS Bedrock AgentCore Runtime（direct code deploy，不用 Docker）。它只做一件事：
把呼叫端已經在本機真的做完 BM25 檢索、真的驗證過原文的結果，轉成自然語言答案。

刻意不用 bedrock_agentcore SDK（BedrockAgentCoreApp），因為那個套件依賴
pydantic-core／uvicorn／websockets 這類需要編譯的套件，要打包成 AgentCore
要求的 arm64 執行檔會多一層跨平台編譯的麻煩。改用標準函式庫的
http.server 直接實作契約要求的兩個路徑：
  - GET  /ping         健康檢查
  - POST /invocations  唯一的業務邏輯入口

只依賴 boto3／botocore（純 Python，沒有編譯過的擴充套件），跨平台打包不會
遇到 wheel 架構不符的問題。

契約細節見：
https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3

PORT = 8080
DEFAULT_MODEL_ID = os.environ.get(
    'BEDROCK_MODEL_ID', 'us.anthropic.claude-haiku-4-5-20251001-v1:0'
)
DEFAULT_REGION = os.environ.get('AWS_REGION', os.environ.get('AWS_DEFAULT_REGION', 'us-west-2'))
MAX_OUTPUT_TOKENS = 512

SYSTEM_PROMPT = (
    '你是台灣訴願案件輔助系統裡的一個文字生成元件。'
    '你只能依據使用者訊息裡「context」欄位提供的內容作答，不能使用任何你自己知道的法規或案例知識。'
    '如果 context 是空的，或者你覺得內容不足以支持問題，就明確說「本地資料不足以回答」，不要編造。'
    '回答要簡短、口語、不要加免責聲明樣板句以外的贅字。'
)

_bedrock_runtime = None


def _bedrock_client():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client('bedrock-runtime', region_name=DEFAULT_REGION)
    return _bedrock_runtime


def generate_answer(prompt: str, context: str, model_id: str = DEFAULT_MODEL_ID) -> str:
    """呼叫 Bedrock 的 converse API，回傳純文字答案。

    `context` 是呼叫端（caseapi 後端）已經用本機 BM25 對 r3 語料真的查過、
    真的開啟過原文之後拿到的內容；這個函式不做任何額外的檢索或工具呼叫，
    只負責把 prompt + context 轉成一段自然語言回答。
    """
    user_text = f'問題：{prompt}\n\ncontext（已驗證的檢索結果，可能為空）：\n{context or "（無）"}'
    response = _bedrock_client().converse(
        modelId=model_id,
        system=[{'text': SYSTEM_PROMPT}],
        messages=[{'role': 'user', 'content': [{'text': user_text}]}],
        inferenceConfig={'maxTokens': MAX_OUTPUT_TOKENS, 'temperature': 0.2},
    )
    content = response['output']['message']['content']
    return ''.join(block.get('text', '') for block in content).strip()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        # AgentCore 自動收集 stdout/stderr 到 CloudWatch；保留預設行為即可。
        super().log_message(format, *args)

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        if self.path != '/ping':
            self._respond(404, {'error': 'not found'})
            return
        self._respond(200, {'status': 'Healthy'})

    def do_POST(self) -> None:  # noqa: N802 - stdlib method name
        if self.path != '/invocations':
            self._respond(404, {'error': 'not found'})
            return
        length = int(self.headers.get('Content-Length', '0') or '0')
        raw_body = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw_body or b'{}')
        except json.JSONDecodeError:
            self._respond(400, {'error': 'invalid JSON body'})
            return
        prompt = payload.get('prompt', '')
        context = payload.get('context', '')
        model_id = payload.get('model_id') or DEFAULT_MODEL_ID
        try:
            answer = generate_answer(prompt, context, model_id=model_id)
        except Exception as exc:  # noqa: BLE001 - 頂層錯誤轉成 500，不讓行程崩潰
            self._respond(500, {'error': f'{type(exc).__name__}: {exc}'})
            return
        self._respond(200, {'response': answer, 'status': 'success'})

    def _respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    server = ThreadingHTTPServer(('0.0.0.0', PORT), _Handler)  # noqa: S104 - AgentCore 契約要求監聽 0.0.0.0
    server.serve_forever()


if __name__ == '__main__':
    main()
