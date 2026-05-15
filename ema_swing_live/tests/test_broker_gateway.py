import os
import unittest
from unittest.mock import patch

from ema_swing_live.app import create_app


class BrokerGatewayTests(unittest.TestCase):
    def test_gateway_endpoint_requires_token(self):
        app = create_app()
        app.config["TESTING"] = True

        with patch.dict(os.environ, {"EMA_SWING_BROKER_GATEWAY_TOKEN": "secret"}, clear=False):
            response = app.test_client().post(
                "/api/broker-gateway",
                json={"operation": "icici.credentials_status"},
            )

        self.assertEqual(response.status_code, 403)

    def test_gateway_endpoint_rejects_unknown_operation(self):
        app = create_app()
        app.config["TESTING"] = True

        with patch.dict(os.environ, {"EMA_SWING_BROKER_GATEWAY_TOKEN": "secret"}, clear=False):
            response = app.test_client().post(
                "/api/broker-gateway",
                json={"operation": "unknown"},
                headers={"X-EMA-Swing-Broker-Gateway-Token": "secret"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported broker gateway operation", response.get_json()["error"])

    def test_icici_status_uses_gateway_when_configured(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        with client.session_transaction() as session:
            session["authenticated"] = True

        env = {
            "EMA_SWING_BROKER_GATEWAY_URL": "http://gateway.example",
            "EMA_SWING_BROKER_GATEWAY_TOKEN": "secret",
            "EMA_SWING_BROKER_GATEWAY_ICICI": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("ema_swing_live.app.broker_gateway.call", return_value={"credentials": {"configured": True}}) as call:
                response = client.get("/api/icici/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["credentials"]["configured"])
        call.assert_called_once_with("icici.credentials_status")


if __name__ == "__main__":
    unittest.main()
