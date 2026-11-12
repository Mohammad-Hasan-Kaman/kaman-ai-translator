"""Offline model-selection regressions through the real compatible HTTP engine."""
import json
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaman_core as core


class CatalogHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.server.requests.append(("GET", self.path, None))
        self.reply(self.server.catalog, self.server.catalog_status)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(("POST", self.path, payload))
        self.reply({"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})


class ModelDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CatalogHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.previous_language = core.get_language()
        core.set_language("en")
        self.addCleanup(core.set_language, self.previous_language)
        self.server.catalog = {"data": []}
        self.server.catalog_status = 200
        self.server.requests = []
        # Only the loopback fixture is contacted, regardless of a developer's proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        patcher = mock.patch.object(core.urllib.request, "urlopen", opener.open)
        patcher.start()
        self.addCleanup(patcher.stop)

    def engine(self, model=""):
        return core.OpenAICompatEngine(self.base_url, "fixture-placeholder", model)

    def assert_no_automatic_post(self, catalog):
        self.server.catalog = catalog
        engine = self.engine()
        with self.assertRaises(core.TranslationError):
            engine.generate("fixture", json_mode=False)
        self.assertEqual(engine.model, "")
        self.assertEqual([r[0] for r in self.server.requests], ["GET"])

    def test_mixed_catalog_skips_non_chat_and_unknown_entries(self):
        self.server.catalog = {"data": [
            {"id": "embedding-first", "capabilities": ["embeddings"]},
            {"id": "speech-second", "supported_endpoints": ["/v1/audio/speech"]},
            {"id": "image-third", "capabilities": {"chat": False}},
            {"id": "unknown-fourth"},
            {"id": "translator", "capabilities": {"chat": True}},
        ]}
        engine = self.engine()
        self.assertEqual(engine.generate("fixture"), "OK")
        self.assertEqual(engine.model, "translator")
        self.assertEqual(self.server.requests[1][1], "/v1/chat/completions")
        self.assertEqual(self.server.requests[1][2]["model"], "translator")
        self.assertEqual(self.server.requests[1][2]["response_format"], {"type": "json_object"})

    def test_chat_capability_list_is_recognized(self):
        self.server.catalog = {"data": [{"id": "chat-list", "capabilities": ["tools", "chat"]}]}
        self.assertEqual(self.engine()._discover_model(), "chat-list")

    def test_chat_endpoint_metadata_is_recognized(self):
        for endpoint in ("/v1/chat/completions", "/chat/completions"):
            with self.subTest(endpoint=endpoint):
                self.server.catalog = {"data": [{"id": "chat-endpoint", "supported_endpoints": [endpoint]}]}
                self.assertEqual(self.engine()._discover_model(), "chat-endpoint")

    def test_explicit_false_chat_capability_overrides_endpoint_hint(self):
        self.assert_no_automatic_post({"data": [{"id": "conflict", "capabilities": {"chat": False},
                                                "supported_endpoints": ["/v1/chat/completions"]}]})

    def test_first_explicit_chat_entry_keeps_server_order(self):
        self.server.catalog = {"data": [{"id": name, "capabilities": ["chat"]} for name in ("second-name", "first-name")]}
        self.assertEqual(self.engine()._discover_model(), "second-name")

    def test_model_ids_alone_require_manual_entry(self):
        self.server.catalog = {"data": [{"id": "looks-like-a-chat-model"}]}
        with self.assertRaisesRegex(core.TranslationError, "Settings -> Model"):
            self.engine().generate("fixture")
        self.assertEqual(len(self.server.requests), 1)

    def test_string_model_list_requires_manual_entry(self):
        self.assert_no_automatic_post({"models": ["chat-looking-name", "embedding-looking-name"]})

    def test_non_chat_catalog_requires_manual_entry(self):
        self.assert_no_automatic_post({"data": [{"id": "embedding", "capabilities": ["embedding"]},
                                                {"id": "speech", "capabilities": {"chat": False}}]})

    def test_truthy_or_malformed_capabilities_do_not_prove_chat_support(self):
        for capabilities in ({"chat": "true"}, {"chat": 1}, "chat", None, 42, {"chat": []}):
            with self.subTest(capabilities=capabilities):
                self.server.requests = []
                self.assert_no_automatic_post({"data": [{"id": "model", "capabilities": capabilities}]})

    def test_malformed_endpoint_values_do_not_prove_chat_support(self):
        for endpoints in ("/v1/chat/completions", None, [None, {}, 42], ["/v1/embeddings"]):
            with self.subTest(endpoints=endpoints):
                self.server.requests = []
                self.assert_no_automatic_post({"data": [{"id": "model", "supported_endpoints": endpoints}]})

    def test_legacy_models_container_and_name_field_are_supported(self):
        self.server.catalog = {"models": [{"name": " local-chat ", "capabilities": {"chat": True}}]}
        self.assertEqual(self.engine()._discover_model(), "local-chat")

    def test_malformed_rows_and_empty_ids_are_skipped(self):
        self.server.catalog = {"data": [None, 9, {}, {"id": " ", "capabilities": ["chat"]},
                                       {"id": 42, "capabilities": ["chat"]},
                                       {"id": "valid", "capabilities": ["chat"]}]}
        self.assertEqual(self.engine()._discover_model(), "valid")

    def test_empty_or_malformed_catalog_stops_before_generation(self):
        for catalog in ({}, {"data": []}, None, [], {"data": 17}, {"data": {"id": "not-a-list"}}):
            with self.subTest(catalog=catalog):
                self.server.requests = []
                self.assert_no_automatic_post(catalog)

    def test_explicit_model_bypasses_discovery_and_is_sent_unchanged(self):
        self.server.catalog_status = 401
        engine = self.engine("operator-selected-model")
        self.assertEqual(engine.generate("fixture", json_mode=False), "OK")
        self.assertEqual([r[0] for r in self.server.requests], ["POST"])
        self.assertEqual(self.server.requests[0][2]["model"], "operator-selected-model")

    def test_selected_model_is_reused_without_a_second_catalog_request(self):
        self.server.catalog = {"data": [{"id": "chat", "capabilities": ["chat"]}]}
        engine = self.engine()
        engine.generate("first", json_mode=False)
        engine.generate("second", json_mode=False)
        self.assertEqual([r[0] for r in self.server.requests], ["GET", "POST", "POST"])

    def test_discovery_http_failure_remains_a_translation_error(self):
        self.server.catalog_status = 401
        with self.assertRaises(core.TranslationError):
            self.engine().generate("fixture", json_mode=False)
        self.assertEqual([r[0] for r in self.server.requests], ["GET"])

    def test_manual_selection_error_is_localized_for_both_ui_languages(self):
        self.server.catalog = {"data": [{"id": "unknown"}]}
        for language in ("fa", "en"):
            with self.subTest(language=language):
                core.set_language(language)
                with self.assertRaises(core.TranslationError) as raised:
                    self.engine()._discover_model()
                self.assertEqual(str(raised.exception), core.msg("model_chat_not_identified"))


if __name__ == "__main__":
    unittest.main()
