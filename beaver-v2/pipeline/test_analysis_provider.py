import json
import unittest
from unittest import mock

import analyze
import config


VALID = json.dumps({
    "coreLines": ["핵심 내용이에요."],
    "verdict": "신중",
    "stockOpinions": [],
    "beaverLine": "확인이 더 필요한 구간이에요.",
}, ensure_ascii=False)


class AnalysisProviderTest(unittest.TestCase):
    def test_local_success_does_not_call_gemini(self):
        with mock.patch.object(config, "ANALYSIS_PROVIDER", "local-first"), \
             mock.patch.object(config, "OLLAMA_MODEL", "qwen3:14b"), \
             mock.patch.object(analyze, "_generate_ollama", return_value=VALID), \
             mock.patch.object(analyze, "_generate_gemini") as gemini:
            result = analyze.analyze_video("자막")
        self.assertEqual(result["verdict"], "신중")
        self.assertEqual(analyze.LAST_GENERATION_PROVIDER, "ollama:qwen3:14b")
        gemini.assert_not_called()

    def test_invalid_local_output_falls_back_to_gemini(self):
        with mock.patch.object(config, "ANALYSIS_PROVIDER", "local-first"), \
             mock.patch.object(config, "GEMINI_MODEL", "gemini-test"), \
             mock.patch.object(analyze, "_working", None), \
             mock.patch.object(analyze, "_generate_ollama", return_value='{"verdict":"신중"}'), \
             mock.patch.object(analyze, "_generate_gemini", return_value=VALID) as gemini:
            result = analyze.analyze_video("자막")
        self.assertEqual(result["verdict"], "신중")
        self.assertTrue(analyze.LAST_GENERATION_PROVIDER.startswith("gemini:"))
        gemini.assert_called_once()

    def test_ollama_only_never_calls_gemini(self):
        with mock.patch.object(config, "ANALYSIS_PROVIDER", "ollama"), \
             mock.patch.object(analyze, "_generate_ollama", side_effect=RuntimeError("offline")), \
             mock.patch.object(analyze, "_generate_gemini") as gemini:
            with self.assertRaises(RuntimeError):
                analyze.analyze_video("자막")
        gemini.assert_not_called()

    def test_openrouter_provider_uses_openrouter_only(self):
        with mock.patch.object(config, "ANALYSIS_PROVIDER", "openrouter"), \
             mock.patch.object(config, "OPENROUTER_MODEL", "google/gemini-2.5-flash"), \
             mock.patch.object(analyze, "_generate_openrouter", return_value=VALID) as openrouter, \
             mock.patch.object(analyze, "_generate_ollama") as ollama, \
             mock.patch.object(analyze, "_generate_gemini") as gemini:
            result = analyze.analyze_video("자막")
        self.assertEqual(result["verdict"], "신중")
        self.assertEqual(analyze.LAST_GENERATION_PROVIDER, "openrouter:google/gemini-2.5-flash")
        openrouter.assert_called_once()
        ollama.assert_not_called()
        gemini.assert_not_called()

    def test_stock_opinion_maps_neutral_to_cautious(self):
        payload = json.dumps({
            "mentioned": True,
            "stance": "중립",
            "summary": "관망 의견이에요.",
            "evidence": "추가 확인이 필요하다고 말했어요.",
        }, ensure_ascii=False)
        with mock.patch.object(analyze, "_generate", return_value=payload):
            result = analyze.analyze_stock_opinion("삼성전자", ["삼성전자"], "자막")
        self.assertEqual(result["stance"], "신중")


if __name__ == "__main__":
    unittest.main()
