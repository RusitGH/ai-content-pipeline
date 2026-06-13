import unittest
from datetime import datetime
from pathlib import Path

import pipeline


class PipelineDefaultsTest(unittest.TestCase):
    def test_spiritual_is_default_mode(self):
        self.assertEqual(pipeline.DEFAULT_MODE, "spiritual")

    def test_daily_spiritual_topic_is_stable_for_same_day(self):
        day = datetime(2026, 6, 13)
        self.assertEqual(
            pipeline.daily_spiritual_topic(day),
            pipeline.daily_spiritual_topic(day),
        )

    def test_placeholder_env_values_are_not_configured(self):
        self.assertFalse(pipeline.is_configured("your_anthropic_key_here"))
        self.assertFalse(pipeline.is_configured(""))
        self.assertTrue(pipeline.is_configured("real-looking-value"))

    def test_spiritual_mode_does_not_use_anthropic_by_default(self):
        self.assertFalse(pipeline.uses_anthropic("spiritual"))

    def test_local_tts_is_default(self):
        self.assertFalse(pipeline.uses_elevenlabs())

    def test_legacy_modes_still_use_anthropic(self):
        self.assertTrue(pipeline.uses_anthropic("reddit"))

    def test_template_script_creates_upload_ready_fields(self):
        scripted = pipeline.write_spiritual_template_script(
            {
                "mode": "spiritual",
                "topic": "karma",
                "title": "Karma in the Bhagavad Gita",
                "body": "Source text from Tavily.",
                "source": "https://example.com",
            }
        )

        self.assertEqual(scripted["script_engine"], "template")
        self.assertIn("karma", scripted["script"])
        self.assertIn("#BhagavadGita", scripted["hashtags"])
        self.assertGreaterEqual(len(scripted["script"].split()), 120)


class UploadMetadataTest(unittest.TestCase):
    def test_normalize_hashtags_adds_defaults_and_hash_prefix(self):
        tags = pipeline.normalize_hashtags(["gita", "#Inner Peace", ""])

        self.assertIn("#gita", tags)
        self.assertIn("#InnerPeace", tags)
        self.assertIn("#BhagavadGita", tags)
        self.assertLessEqual(len(tags), 8)

    def test_build_upload_metadata_contains_platform_payloads(self):
        content = {
            "mode": "spiritual",
            "source": "https://example.com/gita",
            "title": "A Gita verse about courage",
        }
        scripted = {
            "video_title": "The Gita's Courage Lesson",
            "hook": "When fear gets loud, the Gita gives one quiet answer.",
            "script": "When fear gets loud, the Gita gives one quiet answer. Do your duty with a steady mind.",
            "hashtags": ["#Gita", "wisdom"],
        }

        metadata = pipeline.build_upload_metadata(
            content,
            scripted,
            Path("output/example/final_video.mp4"),
            61.234,
        )

        self.assertEqual(metadata["publish_status"], "ready_to_upload")
        self.assertEqual(metadata["content_lane"], "gita_spiritual")
        self.assertEqual(metadata["duration_seconds"], 61.23)
        self.assertIn("tiktok", metadata["platforms"])
        self.assertIn("instagram_reels", metadata["platforms"])
        self.assertIn("youtube_shorts", metadata["platforms"])
        self.assertEqual(
            metadata["platforms"]["youtube_shorts"]["category"],
            "Education",
        )


class SpiritualVisualDirectionTest(unittest.TestCase):
    def test_spiritual_queries_prioritize_indian_sacred_imagery(self):
        queries = pipeline.spiritual_visual_queries(["nature", "ancient indian temple"])

        self.assertIn("ancient indian temple", queries)
        self.assertIn("hindu god statue", queries)
        self.assertIn("rajasthan palace", queries)
        self.assertNotIn("nature", queries)

    def test_grayscale_average_color_is_rejected(self):
        self.assertFalse(pipeline.is_colorful_photo({"avg_color": "#777777"}))
        self.assertTrue(pipeline.is_colorful_photo({"avg_color": "#C06A28"}))

    def test_hex_color_saturation_handles_invalid_values(self):
        self.assertEqual(pipeline.hex_color_saturation("#777777"), 0.0)
        self.assertGreater(pipeline.hex_color_saturation("#C06A28"), 0.5)
        self.assertEqual(pipeline.hex_color_saturation("not-a-color"), 1.0)


class FfmpegOutputParsingTest(unittest.TestCase):
    def test_audio_duration_regex_matches_ffmpeg_duration_line(self):
        output = "Duration: 00:01:02.34, start: 0.000000, bitrate: 128 kb/s"
        match = pipeline.re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)

        self.assertIsNotNone(match)
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        self.assertEqual(duration, 62.34)


class CaptionStyleTest(unittest.TestCase):
    def test_caption_chunks_keep_subtitles_short(self):
        chunks = pipeline.caption_chunks(
            "The Gita keeps bringing us back to this quiet strength. "
            "Do the right thing with sincerity and release what you cannot control."
        )

        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk.split()) <= 8 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
