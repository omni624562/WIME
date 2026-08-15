#! python3
# 候選窗主題共用邏輯。原本重複於 cinbase/__init__.py 與
# input_methods/chewing/chewing_ime.py，抽出成單一模組（重構 B）。
# 位於 python/ 頂層，兩個後端皆可直接 import。

import time

# 舊版淺色候選窗的固定配色（早期版本存在使用者設定裡的 candidateColors）。
# 用來辨識「使用者其實沒自訂、只是舊預設」的情況，好讓新的主題色能生效。
LEGACY_LIGHT_CANDIDATE_COLORS = {
    "panelBackground": "#FFFFFF",
    "panelBorder": "#DADDE3",
    "textPrimary": "#20242A",
    "textSecondary": "#6B7280",
    "highlightBackground": "#DCEBFF",
    "highlightBorder": "#9CC7FF",
    "highlightText": "#0B3A75",
}


_systemThemeCache = {"light": None, "ts": 0.0}


def systemPrefersLightTheme():
    """讀取 Windows 深淺色設定（AppsUseLightTheme），5 秒內快取避免頻繁碰 registry。"""
    now = time.time()
    if _systemThemeCache["light"] is not None and now - _systemThemeCache["ts"] < 5.0:
        return _systemThemeCache["light"]
    light = False
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            light = bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except Exception:
        light = False
    _systemThemeCache["light"] = light
    _systemThemeCache["ts"] = now
    return light


def resolveCandidateTheme(cfg):
    """把「跟隨系統」主題解析成實際主題名，其餘原樣傳回。"""
    theme = str(getattr(cfg, 'candidateTheme', '') or '')
    normalized = ''.join(ch.lower() for ch in theme if ch.isalnum())
    if normalized in ('system', 'followsystem', 'auto'):
        return "Light" if systemPrefersLightTheme() else "Graphite"
    return theme


def candidateColorsForTheme(cfg):
    colors = getattr(cfg, 'candidateColors', {})
    if not isinstance(colors, dict) or not colors:
        return {}

    theme = ''.join(ch.lower() for ch in str(getattr(cfg, 'candidateTheme', '')) if ch.isalnum())
    legacyKeys = set(LEGACY_LIGHT_CANDIDATE_COLORS.keys())
    if set(colors.keys()) == legacyKeys:
        legacyColors = True
        for key, value in LEGACY_LIGHT_CANDIDATE_COLORS.items():
            if str(colors.get(key, '')).strip().lower() != value.lower():
                legacyColors = False
                break
        if legacyColors and theme not in ('', 'light'):
            return {}
    return colors


__all__ = [
    "LEGACY_LIGHT_CANDIDATE_COLORS",
    "systemPrefersLightTheme",
    "resolveCandidateTheme",
    "candidateColorsForTheme",
]
