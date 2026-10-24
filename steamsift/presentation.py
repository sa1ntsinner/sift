"""Localized presentation of the engine's text-free history and verdicts."""
from .i18n import t
from .recommender import Verdict, verdict


def verdict_text(value: Verdict) -> str:
    if not value.kind:
        return ""
    return f"{t('vd_' + value.kind)} · {t('vr_' + value.reason, n=value.value)}"


STYLE = {"hot": "bold magenta", "great": "bold bright_green", "ok": "", "meh": "yellow", "nope": "red"}


def verdict_parts(cut, hist, value=None) -> tuple[str, str, str]:
    """(short label, its style, reason) — the label fits a narrow table column."""
    value = value or verdict(cut, hist)
    if not value.kind:
        return "", "", ""
    return t("vd_" + value.kind), STYLE.get(value.kind, ""), t("vr_" + value.reason, n=value.value)


def verdict_display(cut, hist, value=None):
    value = value or verdict(cut, hist)
    return verdict_text(value), {"hot": "bold magenta", "great": "bold bright_green", "ok": "",
                                 "meh": "yellow", "nope": "red"}.get(value.kind, "")


def cadence_badge(hist):
    if hist.tier == "rare":
        return t("vr_rare", n=hist.sales_2y)
    if hist.gap_days:
        if hist.tier == "frequent":
            return t("cad_frequent_weeks", w=max(1, round(hist.gap_days / 7)))
        return t("cad_occasional_months", m=max(1, round(hist.gap_days / 30)))
    return ""
