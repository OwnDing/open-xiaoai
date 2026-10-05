import unittest

from xiaozhi.services.audio.kws.keywords import keyword_line


class KeywordLineTests(unittest.TestCase):
    def test_threshold_only_for_the_listed_keyword(self):
        thresholds = {"你好小七": 0.1}
        self.assertEqual(keyword_line("你好小七", ["你", "好", "小", "七"], thresholds), "你 好 小 七 #0.1 @你好小七")
        self.assertEqual(keyword_line("你好小爱", ["你", "好", "小", "爱"], thresholds), "你 好 小 爱 @你好小爱")

    def test_english_keyword_keeps_its_bare_tokens(self):
        self.assertEqual(keyword_line("hi siri", ["▁HI", "▁S", "I", "RI"], {}), "▁HI ▁S I RI")
        self.assertEqual(keyword_line("hi siri", ["▁HI", "▁S", "I", "RI"], {"hi siri": 0.3}), "▁HI ▁S I RI #0.3")


if __name__ == "__main__":
    unittest.main()
