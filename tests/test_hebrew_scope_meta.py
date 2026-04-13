from config import (
    hebrew_scope_meta_summary_skip_reason,
    should_reject_hebrew_scope_meta_summary,
)


def test_onet_style_meta_line_rejected():
    s = "אין מעורבות פולנית ישירה במידע המסופק."
    assert should_reject_hebrew_scope_meta_summary(s) is True


def test_normal_poland_story_not_rejected():
    s = (
        "ממשלת פולין אישרה את הרפורמה; האופוזיציה מתכננת הפגנה בוורשאה ביום ראשון "
        "בהשתתפות אלפים."
    )
    assert should_reject_hebrew_scope_meta_summary(s) is False


def test_skip_reason_prefix_exempt():
    assert hebrew_scope_meta_summary_skip_reason().lower().startswith("scope meta:")
