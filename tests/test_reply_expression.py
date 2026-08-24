import unittest

from pandausagies_v2.reply_expression import LocalReplyExpressionProvider, classify_reply_intent, validate_reply_candidate


class ReplyExpressionTests(unittest.TestCase):
    def test_saved_phase7_examples_are_specific_and_valid(self):
        provider=LocalReplyExpressionProvider()
        cases=(("ハロー","greeting","ハロー"),("@pandausagies パン好き？","question","好き\nお弁当のすき間にも入る"))
        for source,intent,expected in cases:
            self.assertEqual(classify_reply_intent(source),intent)
            candidate=provider.generate(source,intent)
            self.assertEqual(candidate,expected)
            self.assertTrue(validate_reply_candidate(source,intent,candidate).valid)

    def test_generic_old_candidate_is_rejected(self):
        result=validate_reply_candidate("ハロー","greeting","読んだ\nありがとう")
        self.assertFalse(result.valid)
        self.assertIn("generic_fallback",result.reasons)

    def test_question_fallback_answers_uncertainty_without_invention(self):
        provider=LocalReplyExpressionProvider(); source="どこにいる？"; intent=classify_reply_intent(source)
        candidate=provider.generate(source,intent)
        self.assertEqual(candidate,"わからない\nもう少し聞きたい")
        self.assertTrue(validate_reply_candidate(source,intent,candidate).valid)


if __name__=="__main__": unittest.main()
