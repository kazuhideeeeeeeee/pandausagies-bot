import unittest

from pandausagies_v2.write_preflight import WritePreflightConfig,validate_post_candidate


class WritePreflightTests(unittest.TestCase):
    def test_social_voice_candidate(self):
        result=validate_post_candidate("パンを買った\n帰るまで少し減った","offbeat",False)
        self.assertTrue(result["valid"])

    def test_promo_links_emoji_and_hashtag_fail(self):
        for text in ("新曲配信中！ https://example.com","パン #昼","パンを買った🙂"):
            self.assertFalse(validate_post_candidate(text,"ordinary",False)["valid"])

    def test_preflight_requires_staging_and_closed_send_gate(self):
        WritePreflightConfig("staging","31849050",False,False,True,False,False).require_safe_preflight()
        with self.assertRaises(RuntimeError): WritePreflightConfig("production","31849050",False,False,True,False,False).require_safe_preflight()
        with self.assertRaises(RuntimeError): WritePreflightConfig("staging","31849050",True,False,True,False,False).require_safe_preflight()


if __name__=="__main__": unittest.main()
