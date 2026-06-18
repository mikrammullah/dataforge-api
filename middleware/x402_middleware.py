import json, base64, logging, httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from typing import Callable

logger = logging.getLogger("x402")

class X402Middleware(BaseHTTPMiddleware):
    USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

    def __init__(self, app, pay_to, amount_usdc, network="base",
                 protected_paths=None, facilitator_url="https://x402.org/facilitator"):
        super().__init__(app)
        self.pay_to = pay_to
        self.amount_usdc = amount_usdc
        self.network = network
        self.protected_paths = protected_paths or ["/"]
        self.facilitator_url = facilitator_url.rstrip("/")
        self.amount_atomic = str(int(float(amount_usdc) * 1_000_000))
        self.asset = self.USDC_BASE if network == "base" else self.USDC_BASE_SEPOLIA

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._is_protected(request.url.path):
            return await call_next(request)
        payment_header = request.headers.get("X-PAYMENT")
        if not payment_header:
            return self._payment_required_response(str(request.url))
        verified, error = await self._verify_payment(payment_header, str(request.url))
        if not verified:
            return self._payment_required_response(str(request.url), error=error)
        return await call_next(request)

    def _is_protected(self, path):
        return any(path.startswith(p) for p in self.protected_paths)

    def _payment_required_response(self, resource_url, error=None):
        body = {
            "x402Version": 1,
            "error": error or "Payment required",
            "accepts": [{
                "scheme": "exact",
                "network": self.network,
                "maxAmountRequired": self.amount_atomic,
                "resource": resource_url,
                "description": f"DataForge API — ${self.amount_usdc} USDC",
                "mimeType": "application/json",
                "payTo": self.pay_to,
                "maxTimeoutSeconds": 300,
                "asset": self.asset,
                "extra": {"name": "DataForge API", "version": "1.0.0"},
            }]
        }
        return JSONResponse(status_code=402, content=body)

    async def _verify_payment(self, payment_header, resource_url):
        try:
            raw = base64.b64decode(payment_header + "==")
            payload = json.loads(raw)
        except Exception as exc:
            return False, f"Malformed header: {exc}"
        if payload.get("x402Version") != 1:
            return False, "Unsupported x402Version"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.post(
                    f"{self.facilitator_url}/verify",
                    json={
                        "x402Version": 1,
                        "paymentPayload": payload,
                        "paymentRequirements": {
                            "scheme": "exact",
                            "network": self.network,
                            "maxAmountRequired": self.amount_atomic,
                            "resource": resource_url,
                            "payTo": self.pay_to,
                            "asset": self.asset,
                            "maxTimeoutSeconds": 300,
                        },
                    },
                )
            data = resp.json()
            if resp.status_code == 200 and data.get("isValid"):
                return True, None
            return False, data.get("invalidReason", "Verification failed")
        except httpx.TimeoutException:
            return False, "Facilitator timeout"
        except Exception as exc:
            logger.error("Facilitator error: %s", exc)
            return False, f"Payment verification unavailable: {exc}"
