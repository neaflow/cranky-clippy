"""Static application and website catalog used by desktop-state detection.

This module defines app categories, app/site metadata, aliases, package/profile
locations, and identity matching. It does not query the desktop, filesystem, or
network; get_desktop_state.py owns those runtime observations.
"""

import re

# App-specific metadata — the extra fields Jev would need for each app to
# judge "distraction or not". Apps whose name is self-explanatory (Discord,
# Slack, etc.) only need generic window data; apps where content varies get
# their own metadata fields.
#
# Structure: APP_METADATA is a dict of app "classes". Each class maps app
# names to a list of metadata fields to collect. Browsers get their own class
# and also have their own sub-class, WEBAPP_METADATA, for sites that are
# opened inside a browser (YouTube, Notion, Reddit, ...). Those sites are not
# apps; they are extra metadata layered on top of the browser's own fields,
# picked out by matching the site_domain.

APP_METADATA = {
    # CLASS: browser. A tab can be anything, so we need to see inside it.
    # Supported: Chrome, Chromium, Firefox, Edge, Safari, Brave, Opera, Arc,
    # Vivaldi. These fields are collected for every browser window, and then
    # WEBAPP_METADATA below adds site-specific fields on top.
    "browser": {
        "chrome": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "chromium": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "firefox": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "edge": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "safari": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "brave": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "opera": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "arc": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "vivaldi": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
    },
    # CLASS: video player (native apps). What's playing and whether it plays.
    "video": {
        "vlc": ["media_title", "playback_state"],
        "mpv": ["media_title", "playback_state"],
    },
    # CLASS: code editor. Which file/branch hints at whether it's the right project.
    "editor": {
        "code": ["workspace_name", "file_path", "git_branch", "active_file_focus_seconds", "language"],
        "jetbrains": ["project_name", "file_path", "git_branch", "tool_window_focused"],
        "sublime_text": ["project_name", "file_path"],
        "notepad++": ["file_path"],
        "vim": ["file_path", "buffer_name"],
        "neovim": ["file_path", "buffer_name"],
        "emacs": ["file_path", "buffer_name"],
        # KDE full IDE with its own window chrome
        "kate": ["file_path", "document_name"],
        "idle": ["file_path", "language"],
        "arduino": ["project_name", "file_path", "board_name"],
    },
    # AI coding environments and agents. Keep these distinct from general
    # conversational assistants and ordinary editors.
    "ai_coding": {
        "opencode": ["workspace_name", "window_context"],
        "antigravity": ["workspace_name", "window_context"],
        "zcode": ["workspace_name", "window_context"],
        "cursor": ["workspace_name", "file_path", "git_branch", "window_context"],
        "windsurf": ["workspace_name", "file_path", "git_branch", "window_context"],
        "zed": ["workspace_name", "file_path", "git_branch", "window_context"],
        "codex": ["workspace_name", "window_context"],
        "claude_code": ["workspace_name", "window_context"],
        "gemini_cli": ["workspace_name", "window_context"],
        "aider": ["workspace_name", "window_context"],
        "goose": ["workspace_name", "window_context"],
        "openhands": ["workspace_name", "window_context"],
        "cline": ["workspace_name", "window_context"],
        "roo_code": ["workspace_name", "window_context"],
        "continue": ["workspace_name", "window_context"],
        "github_copilot": ["workspace_name", "window_context"],
        "kiro": ["workspace_name", "window_context"],
        "devin": ["workspace_name", "window_context"],
        "amp": ["workspace_name", "window_context"],
    },
    # General-purpose conversational AI clients. This records their function
    # without pre-judging whether a particular conversation serves the goal.
    "ai_chat": {
        "chatgpt": ["conversation_title", "model_name"],
        "claude": ["conversation_title", "model_name"],
        "deepseek": ["conversation_title", "model_name"],
        "gemini": ["conversation_title", "model_name"],
        "copilot": ["conversation_title", "model_name"],
        "perplexity": ["conversation_title", "model_name"],
        "grok": ["conversation_title", "model_name"],
        "mistral_le_chat": ["conversation_title", "model_name"],
        "poe": ["conversation_title", "model_name"],
        "qwen_chat": ["conversation_title", "model_name"],
        "meta_ai": ["conversation_title", "model_name"],
        "kimi": ["conversation_title", "model_name"],
        "zai_chat": ["conversation_title", "model_name"],
        "chatbox": ["conversation_title", "model_name"],
        "lm_studio": ["conversation_title", "model_name"],
        "jan": ["conversation_title", "model_name"],
        "msty": ["conversation_title", "model_name"],
    },
    "assistant": {
        "openwork": ["workspace_name", "window_context"],
    },
    # CLASS: game launcher / game. Which game, and is it running or in a menu.
    "game": {
        "steam": ["store_page_url", "game_name", "game_running", "session_state", "time_in_game"],
        "epic_games_launcher": ["store_page_url", "game_name", "game_running"],
        "riot_client": ["store_page_url", "game_name", "game_running"],
        "battledotnet": ["game_name", "game_running"],
        "ea_app": ["game_name", "game_running"],
        "gog_galaxy": ["game_name", "game_running"],
        "minecraft": ["server_name_or_singleplayer", "session_state", "time_in_game"],
        "roblox": ["experience_name", "game_running"],
        # alternative store / installer front ends
        "heroic": ["store_page_url", "game_name", "game_running"],
        # game streaming front ends (Moonlight, GeForce Now style)
        "moonlight": ["host_name", "game_name", "connection_state"],
        "lutris": ["game_name", "game_running"],
        "balatro": ["game_name", "session_state"],
        "cookie_clicker": ["game_name", "session_state"],
        "arknights_endfield": ["game_name", "session_state"],
        "gryph2": ["game_name", "session_state"],
        "hoyoplay": ["game_name", "session_state"],
        "prismlauncher": ["game_name", "session_state"],
    },
    # CLASS: chat / social (native apps). The app is usually the distraction
    # itself, so only the basics plus whether a call is active.
    "chat": {
        "discord": ["server_or_dm_name", "voice_call_active", "streaming"],
        "telegram": ["chat_name"],
        "whatsapp": ["chat_name"],
        "signal": ["chat_name"],
        "vesktop": ["server_or_dm_name", "voice_call_active", "streaming"],
    },
    # Workplace/school collaboration tools have chat UIs but are designed for
    # coordinated work, shared files, meetings, and project communication.
    "collaboration": {
        "teams": ["workspace_name", "channel_or_chat_name", "call_active"],
        "slack": ["workspace_name", "channel_name", "huddle_active"],
        "google_chat": ["workspace_name", "space_or_chat_name"],
        "mattermost": ["workspace_name", "channel_name"],
        "rocketchat": ["workspace_name", "channel_name"],
        "zulip": ["workspace_name", "stream_name"],
    },
    # Mail clients are deliberately separate from chat so quick-check-in
    # treatment only applies to messaging/call apps.
    "email": {
        "thunderbird": ["mail_subject", "mail_folder"],
        "kmail": ["mail_subject", "mail_folder"],
        "evolution": ["mail_subject", "mail_folder"],
        "geary": ["mail_subject", "mail_folder"],
        "mailspring": ["mail_subject", "mail_folder"],
        "claws_mail": ["mail_subject", "mail_folder"],
    },
    # CLASS: document editor / productivity (native apps).
    "document": {
        "word": ["document_name", "doc_focus_seconds"],
        "excel": ["workbook_name", "sheet_name"],
        "powerpoint": ["presentation_name", "slide_number"],
        "onenote": ["notebook_name", "page_title"],
        "obsidian": ["vault_name", "file_path"],
        "libreoffice": ["document_name", "doc_focus_seconds"],
        "texstudio": ["file_path"],
        # document *viewer*, same treatment
        "okular": ["document_name", "file_path", "page_number"],
    },
    # Terminal emulators have their own category: shell work is a common part
    # of coding workflows, not just a generic desktop utility.
    "terminal": {
        "konsole": ["tab_name", "session_context"],
        "xterm": ["tab_name", "session_context"],
        "uxterm": ["tab_name", "session_context"],
        "gnome_terminal": ["tab_name", "session_context"],
        "ptyxis": ["tab_name", "session_context"],
        "kitty": ["tab_name", "session_context"],
        "alacritty": ["tab_name", "session_context"],
        "wezterm": ["tab_name", "session_context"],
        "foot": ["tab_name", "session_context"],
        "tilix": ["tab_name", "session_context"],
        "terminator": ["tab_name", "session_context"],
        "xfce4_terminal": ["tab_name", "session_context"],
        "mate_terminal": ["tab_name", "session_context"],
        "lxterminal": ["tab_name", "session_context"],
        "ghostty": ["tab_name", "session_context"],
        "contour": ["tab_name", "session_context"],
        "rio": ["tab_name", "session_context"],
    },
    # Creative tools can support some goals (e.g. a lab-report figure), but
    # aren't on-task just because they're productive software.
    "creative": {
        "krita": ["document_name", "canvas_name"],
        "cura_slicer": ["model_name", "printer_profile"],
    },
    # CLASS: desktop utilities — the apps standard to a computer: file
    # manager, settings, information tools, system utilities. KDE for now;
    # GNOME / other DEs / Windows / macOS later.
    "desktop": {
        # file manager: which folder the user is in is the main signal
        "dolphin": ["location_path", "location_name"],
        # settings apps: which panel they have open
        "systemsettings": ["panel_name"],
        "kinfocenter": ["panel_name"],
        # image viewer / editor
        "gwenview": ["image_name"],
        "kolourpaint": ["image_name"],
        # git front end: which repo is open
        "github-desktop": ["repo_name"],
        # vpn front end: which panel
        "nordvpn": ["panel_name"],
        # archive manager
        "ark": ["archive_name"],
        # screenshot tool: which capture mode is being prepared
        "spectacle": ["capture_mode"],
        # software store: which store page
        "discover": ["page_name", "package_name"],
        # device pairing tool
        "kdeconnect": ["device_name", "connection_state"],
        # disk tool
        "partitionmanager": ["disk_name", "action_state"],
        "windscribe": ["panel_name"],
        "htop": ["process_name"],
        "barrier": ["tool_name"],
        "input_leap": ["tool_name"],
        "protonplus": ["tool_name"],
        "protonup_qt": ["tool_name"],
        "clicker": ["tool_name"],
        # run dialog / calculator / clipboard helpers: name only
        "_default": ["tool_name"],
    },
}

# WEBAPP_METADATA: sites that aren't apps — they run inside one of the
# browsers above. When the focused browser's site_domain matches one of
# these keys, its fields are added on top of the browser's own fields.
WEBAPP_METADATA = {
    # Video / streaming sites.
    "youtube.com": ["video_title", "channel_name", "video_category", "tab_focus_seconds"],
    "youtube_music": ["track_title", "channel_name", "tab_focus_seconds"],  # music.youtube.com
    "netflix.com": ["show_title", "playback_state", "tab_focus_seconds"],
    "disneyplus.com": ["show_title", "playback_state", "tab_focus_seconds"],
    "twitch.tv": ["streamer_name", "stream_title", "stream_category", "tab_focus_seconds"],
    "spotify.com": ["track_title", "playlist_name", "playback_state"],      # open.spotify.com
    # Social / feeds.
    "x.com": ["feed_type", "profile_viewing"],                              # twitter/x
    "instagram.com": ["reels_active", "dm_active"],
    "tiktok.com": ["video_count_this_session", "session_state"],
    "reddit.com": ["subreddit", "post_title", "site_url", "tab_focus_seconds"],
    "facebook.com": ["feed_type", "chat_name"],
    "snapchat.com": ["chat_name"],
    # Documents / productivity sites.
    "docs.google.com": ["document_name", "editor_active", "tab_focus_seconds"],
    "notion.so": ["page_name", "page_type", "tab_focus_seconds"],
    "notion.com": ["page_name", "page_type", "tab_focus_seconds"],
    "overleaf.com": ["project_name", "file_path", "tab_focus_seconds"],
    "classroom.google.com": ["class_name", "assignment_name"],
    "drive.google.com": ["workspace_name", "file_name", "folder_name"],
    "teams.microsoft.com": ["workspace_name", "channel_name"],
    "teams.live.com": ["workspace_name", "channel_name"],
    "chat.google.com": ["workspace_name", "space_or_chat_name"],
    "app.slack.com": ["workspace_name", "channel_name"],
    "slack.com": ["workspace_name", "channel_name"],
    "onedrive.live.com": ["file_name", "folder_name"],
    "onedrive.com": ["file_name", "folder_name"],
    "word.office.com": ["document_name", "document_state"],
    "office.com": ["workspace_name", "document_name"],
    "microsoft365.com": ["workspace_name", "document_name"],
    "sharepoint.com": ["site_name", "document_name"],
    # Authentication pages are workflow transitions, not destinations.
    "login.microsoftonline.com": ["identity_provider", "authentication_context"],
    "login.live.com": ["identity_provider", "authentication_context"],
    "accounts.google.com": ["identity_provider", "authentication_context"],
    # General-purpose conversational AI websites. Classification describes
    # the site type only; the conversation itself determines relevance.
    "chatgpt.com": ["ai_provider", "conversation_title"],
    "chat.openai.com": ["ai_provider", "conversation_title"],
    "claude.ai": ["ai_provider", "conversation_title"],
    "chat.deepseek.com": ["ai_provider", "conversation_title"],
    "gemini.google.com": ["ai_provider", "conversation_title"],
    "copilot.microsoft.com": ["ai_provider", "conversation_title"],
    "perplexity.ai": ["ai_provider", "conversation_title"],
    "grok.com": ["ai_provider", "conversation_title"],
    "chat.mistral.ai": ["ai_provider", "conversation_title"],
    "poe.com": ["ai_provider", "conversation_title"],
    "chat.qwen.ai": ["ai_provider", "conversation_title"],
    "meta.ai": ["ai_provider", "conversation_title"],
    "kimi.com": ["ai_provider", "conversation_title"],
    "chat.z.ai": ["ai_provider", "conversation_title"],
    "you.com": ["ai_provider", "conversation_title"],
    "character.ai": ["ai_provider", "conversation_title"],
    # Webmail is a separate category from chat, despite running in a browser.
    "mail.google.com": ["mail_provider", "mail_subject"],
    "outlook.live.com": ["mail_provider", "mail_subject"],
    "outlook.office.com": ["mail_provider", "mail_subject"],
    "outlook.office365.com": ["mail_provider", "mail_subject"],
    "mail.yahoo.com": ["mail_provider", "mail_subject"],
    "mail.proton.me": ["mail_provider", "mail_subject"],
    "app.fastmail.com": ["mail_provider", "mail_subject"],
    "mail.zoho.com": ["mail_provider", "mail_subject"],
    "mail.aol.com": ["mail_provider", "mail_subject"],
    # Generic site / not in the list above: browser fields only.
    "_default": [],
}

EMAIL_WEBAPP_PROVIDERS = {
    "mail.google.com": "Gmail",
    "outlook.live.com": "Outlook",
    "outlook.office.com": "Outlook",
    "outlook.office365.com": "Outlook",
    "mail.yahoo.com": "Yahoo Mail",
    "mail.proton.me": "Proton Mail",
    "app.fastmail.com": "Fastmail",
    "mail.zoho.com": "Zoho Mail",
    "mail.aol.com": "AOL Mail",
}
WEBAPP_CATEGORIES = {key: "email" for key in EMAIL_WEBAPP_PROVIDERS}
WEBAPP_CATEGORIES.update({
    "youtube.com": "video",
    "youtube_music": "video",
    "netflix.com": "video",
    "disneyplus.com": "video",
    "twitch.tv": "video",
    "spotify.com": "audio_media",
    "drive.google.com": "file_storage",
    "teams.microsoft.com": "collaboration",
    "teams.live.com": "collaboration",
    "chat.google.com": "collaboration",
    "app.slack.com": "collaboration",
    "slack.com": "collaboration",
    "onedrive.live.com": "file_storage",
    "onedrive.com": "file_storage",
    "word.office.com": "document_editor",
    "office.com": "office_productivity",
    "microsoft365.com": "office_productivity",
    "sharepoint.com": "collaboration",
    "login.microsoftonline.com": "authentication",
    "login.live.com": "authentication",
    "accounts.google.com": "authentication",
})
AI_CHAT_WEBAPP_PROVIDERS = {
    "chatgpt.com": "ChatGPT",
    "chat.openai.com": "ChatGPT",
    "claude.ai": "Claude",
    "chat.deepseek.com": "DeepSeek",
    "gemini.google.com": "Gemini",
    "copilot.microsoft.com": "Microsoft Copilot",
    "perplexity.ai": "Perplexity",
    "grok.com": "Grok",
    "chat.mistral.ai": "Mistral Le Chat",
    "poe.com": "Poe",
    "chat.qwen.ai": "Qwen Chat",
    "meta.ai": "Meta AI",
    "kimi.com": "Kimi",
    "chat.z.ai": "Z.ai Chat",
    "you.com": "You.com AI",
    "character.ai": "Character.AI",
}
AI_CHAT_WEBAPP_DESCRIPTIONS = {
    "chatgpt.com": "ChatGPT is a conversational AI service for questions, explanations, writing, and analysis.",
    "chat.openai.com": "ChatGPT is a conversational AI service for questions, explanations, writing, and analysis.",
    "claude.ai": "Claude is a conversational AI service for questions, writing, analysis, and interactive work with text and files.",
    "chat.deepseek.com": "DeepSeek is a conversational AI service for questions, reasoning, and text generation.",
    "gemini.google.com": "Gemini is a conversational AI service for questions, explanations, writing, and analysis.",
    "copilot.microsoft.com": "Microsoft Copilot is a conversational AI service for questions, writing, and general assistance.",
    "perplexity.ai": "Perplexity is a conversational answer and research service that can provide cited web sources.",
    "grok.com": "Grok is a conversational AI service for questions, analysis, and text generation.",
    "chat.mistral.ai": "Mistral Le Chat is a conversational AI service for questions, writing, and analysis.",
    "poe.com": "Poe is a conversational platform for interacting with multiple AI assistants and models.",
    "chat.qwen.ai": "Qwen Chat is a conversational AI service for questions, explanations, and text generation.",
    "meta.ai": "Meta AI is a conversational assistant for questions and content generation.",
    "kimi.com": "Kimi is a conversational AI service for questions, reasoning, and work with long documents.",
    "chat.z.ai": "Z.ai Chat is a conversational AI service for questions, reasoning, and text generation.",
    "you.com": "You.com provides conversational AI answers and search assistance.",
    "character.ai": "Character.AI provides conversational experiences with user-created AI characters.",
}
WEBAPP_DESCRIPTIONS = {
    "youtube.com": "YouTube hosts educational, instructional, informational, and entertainment videos; relevance depends on the active video or search.",
    "drive.google.com": "Google Drive is a cloud file-storage and file-organization service.",
    "teams.microsoft.com": "Microsoft Teams is a school/work collaboration service for class or team chats, meetings, shared files, assignment information, and project coordination.",
    "teams.live.com": "Microsoft Teams is a school/work collaboration service for class or team chats, meetings, shared files, assignment information, and project coordination.",
    "chat.google.com": "Google Chat is a school/work collaboration service for direct messages, group spaces, and work coordination.",
    "app.slack.com": "Slack is a workplace collaboration service for team channels, direct messages, meetings, and shared work.",
    "slack.com": "Slack is a workplace collaboration service for team channels, direct messages, meetings, and shared work.",
    "onedrive.live.com": "OneDrive is Microsoft's cloud file-storage and file-organization service.",
    "onedrive.com": "OneDrive is Microsoft's cloud file-storage and file-organization service.",
    "word.office.com": "Word for the web is an online document editor.",
    "office.com": "Microsoft 365 is a web portal for accessing Office apps and files.",
    "microsoft365.com": "Microsoft 365 is a web portal for accessing Office apps and files.",
    "sharepoint.com": "SharePoint provides team sites, shared files, and document workspaces.",
    "login.microsoftonline.com": "Microsoft sign-in page used to authenticate to Microsoft services.",
    "login.live.com": "Microsoft account sign-in page used to authenticate to Microsoft services.",
    "accounts.google.com": "Google account sign-in page used to authenticate to Google services.",
}
WEBAPP_DESCRIPTIONS.update({
    domain: "%s is a web email client." % provider
    for domain, provider in EMAIL_WEBAPP_PROVIDERS.items()
})
WEBAPP_DESCRIPTIONS.update(AI_CHAT_WEBAPP_DESCRIPTIONS)
WEBAPP_CATEGORIES.update({key: "ai_chat" for key in AI_CHAT_WEBAPP_PROVIDERS})

# App names that belong to the desktop shell itself, not to a user's app.
# These should be ignored by desktop activity judgments too: launchers and
# panels (for example Plasma's application launcher) are transient system UI.
SHELL_APPS = {
    "kwin", "ksmserver", "plasmashell", "org.kde.plasmashell", "kded6", "kaccess", "ksecretd",
    "xembedsniproxy", "gmenudbusmenuproxy", "ActivityManager", "kwalletd",
    "polkit-kde-authentication-agent-1", "org_kde_powerdevil",
    "xdg-desktop-portal-kde", "xdg-desktop-portal-gtk", "kdeconnect.daemon",
    "xwaylandvideobridge", "kdeconnectd", "discover.notifier", "baloorunner",
    "gcdemu", "kvm", "shell", "org.gnome.Shell", "gnome-shell",
}
_SHELL_APP_IDS = {re.sub(r"[^a-z0-9]", "", app.casefold()) for app in SHELL_APPS}


def _is_shell_app(app_name):
    """Whether an app ID identifies desktop shell/system UI."""
    normalized = re.sub(r"[^a-z0-9]", "", (app_name or "").casefold())
    return normalized in _SHELL_APP_IDS

# Window-title suffixes -> canonical APP_METADATA key, so
# "Page title - Chromium" identifies the app as a browser even if the
# AT-SPI app id looks odd, and gives us the active tab's title.
TITLE_SUFFIXES = {
    "google chrome": "chrome",
    "chrome canary": "chrome",
    "chromium": "chromium",
    "mozilla firefox": "firefox",
    "firefox": "firefox",
    "microsoft edge": "edge",
    "brave": "brave",
    "opera gx": "opera",
    "opera": "opera",
    "arc": "arc",
    "vivaldi": "vivaldi",
    "safari": "safari",
    "visual studio code": "code",
    "thunderbird": "thunderbird",
    "mozilla thunderbird": "thunderbird",
    "kmail": "kmail",
    "evolution": "evolution",
    "geary": "geary",
    "mailspring": "mailspring",
    "claws mail": "claws_mail",
    "microsoft teams": "teams",
    "teams": "teams",
    "uxterm": "uxterm",
    "konsole": "konsole",
    "xterm": "xterm",
    "gnome terminal": "gnome_terminal",
    "gnome-terminal": "gnome_terminal",
    "ptyxis": "ptyxis",
    "kitty": "kitty",
    "alacritty": "alacritty",
    "wezterm": "wezterm",
    "foot": "foot",
    "tilix": "tilix",
    "terminator": "terminator",
    "xfce terminal": "xfce4_terminal",
    "mate terminal": "mate_terminal",
    "lxterminal": "lxterminal",
    "ghostty": "ghostty",
    "contour": "contour",
    "rio": "rio",
    "opencode": "opencode",
    "open code": "opencode",
    "antigravity": "antigravity",
    "zcode": "zcode",
    "zed": "zed",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "codex": "codex",
    "claude code": "claude_code",
    "gemini cli": "gemini_cli",
    "chatgpt": "chatgpt",
    "claude": "claude",
    "deepseek": "deepseek",
    "perplexity": "perplexity",
}

# Key: normalized app id -> APP_METADATA key. AT-SPI app names vary
# ("code", "Code", ...) so everything goes through this map first.
APP_ALIASES = {
    "vscode": "code",
    "visual-studio-code": "code",
    "google-chrome": "chrome",
    "microsoft-edge": "edge",
    # package/form ids that don't split into a known token
    "zenbrowser": "zen",
    "waterfox-current": "waterfox",
    "waterfox-classic": "waterfox",
    "nordvpn-gui": "nordvpn",
    "hgl": "heroic",   # Heroic Games Launcher flatpak window class
    "github desktop": "github-desktop",
    "githubdesktop": "github-desktop",
    "claws-mail": "claws_mail",
    "google-antigravity": "antigravity",
    "openai-codex": "codex",
    "codex-cli": "codex",
    "claude-code": "claude_code",
    "claude code": "claude_code",
    "gemini-cli": "gemini_cli",
    "gemini cli": "gemini_cli",
    "roo-code": "roo_code",
    "roocode": "roo_code",
    "github-copilot": "github_copilot",
    "github copilot": "github_copilot",
    "aider-chat": "aider",
    "goose-cli": "goose",
    "chat gpt": "chatgpt",
    "deepseek chat": "deepseek",
    "mistral le chat": "mistral_le_chat",
    "mistral-chat": "mistral_le_chat",
    "qwen chat": "qwen_chat",
    "meta ai": "meta_ai",
    "z.ai chat": "zai_chat",
    "lm studio": "lm_studio",
    "cookie clicker": "cookie_clicker",
    "cookie-clicker": "cookie_clicker",
    "idle-python3.13": "idle",
    "processing-app-base": "arduino",
    "com.differentai.openwork": "openwork",
    "net.lutris.lutris": "lutris",
    "net.lutris.arknights-endfield-3": "arknights_endfield",
    "net.lutris.gryph2-4": "gryph2",
    "net.lutris.hoyoplay-2": "hoyoplay",
    "net.lutris.hoyoplay-5": "hoyoplay",
    "steam_app_2379780": "balatro",
    "steam_app_1454400": "cookie_clicker",
    "steam_app_280680": "krita",
    "cura-slicer": "cura_slicer",
    "prismlauncher-alpo": "prismlauncher",
    "io.github.input_leap.input-leap": "input_leap",
    "input-leap": "input_leap",
    "net.davidotek.pupgui2": "protonup_qt",
    "com.vysp3r.protonplus": "protonplus",
    "com.github.debauchee.barrier": "barrier",
    "net.codelogistics.clicker": "clicker",
    "org.gnome.terminal": "gnome_terminal",
    "org.gnome.ptyxis": "ptyxis",
    "org.alacritty.alacritty": "alacritty",
    "org.wezfurlong.wezterm": "wezterm",
    "com.mitchellh.ghostty": "ghostty",
    "org.kde.konsole": "konsole",
    "xfce4-terminal": "xfce4_terminal",
    "mate-terminal": "mate_terminal",
}

# Short, concrete descriptions are included in app_metadata so Jev does not
# have to infer what a less-common installed program is from its name.
APP_DESCRIPTIONS = {
    "opencode": "OpenCode is an AI coding agent available as a terminal, desktop, and IDE tool for working with software projects.",
    "antigravity": "Antigravity is an agentic software-development environment with an editor and agents that work across code, terminal, and browser.",
    "openwork": "OpenWork is a desktop workspace for running AI agents, skills, and MCP-connected workflows on files and projects.",
    "zcode": "ZCode is a software-development workbench with an integrated coding agent.",
    "zed": "Zed is a code editor with integrated AI-assisted and agentic coding features.",
    "cursor": "Cursor is an AI-focused code editor with coding-agent features.",
    "windsurf": "Windsurf is an AI-focused code editor and agentic software-development environment.",
    "codex": "OpenAI Codex is a coding agent available through terminal, IDE, and desktop integrations.",
    "claude_code": "Claude Code is Anthropic's coding agent for working with software projects through terminal and IDE integrations.",
    "gemini_cli": "Gemini CLI is Google's terminal-based AI coding agent for software-development tasks.",
    "aider": "Aider is a terminal-based AI pair-programming tool that edits software repositories.",
    "goose": "Goose is an extensible AI agent that can use development tools and operate on software projects.",
    "openhands": "OpenHands is an open-source software-development agent platform.",
    "cline": "Cline is an IDE coding-agent extension that can work with files and development tools.",
    "roo_code": "Roo Code is an IDE coding-agent extension with configurable software-development modes.",
    "continue": "Continue is an AI coding assistant and agent integrated with code editors.",
    "github_copilot": "GitHub Copilot is an AI coding assistant integrated into supported code editors.",
    "kiro": "Kiro is an AI-powered IDE and agentic software-development environment.",
    "devin": "Devin is an AI software-engineering agent and development environment.",
    "amp": "Amp is an AI coding agent for software-development tasks.",
    "chatgpt": "ChatGPT is a conversational AI assistant for questions, explanations, writing, and analysis.",
    "claude": "Claude is a conversational AI assistant for questions, writing, analysis, and interactive work with text and files.",
    "deepseek": "DeepSeek is a conversational AI assistant for questions, reasoning, and text generation.",
    "gemini": "Gemini is a conversational AI assistant for questions, explanations, writing, and analysis.",
    "copilot": "Microsoft Copilot is a conversational AI assistant for questions, writing, and general assistance.",
    "perplexity": "Perplexity is a conversational answer and research service that can provide cited web sources.",
    "grok": "Grok is a conversational AI assistant for questions, analysis, and text generation.",
    "mistral_le_chat": "Mistral Le Chat is a conversational AI assistant for questions, writing, and analysis.",
    "poe": "Poe is a conversational platform for interacting with multiple AI assistants and models.",
    "qwen_chat": "Qwen Chat is a conversational AI assistant for questions, explanations, and text generation.",
    "meta_ai": "Meta AI is a conversational assistant for questions and content generation.",
    "kimi": "Kimi is a conversational AI assistant for questions, reasoning, and work with long documents.",
    "zai_chat": "Z.ai Chat is a conversational AI assistant for questions, reasoning, and text generation.",
    "chatbox": "Chatbox is a desktop client for conversations with AI models.",
    "lm_studio": "LM Studio is a desktop application for running local models and chatting with them.",
    "jan": "Jan is a desktop AI assistant for chatting with local and hosted models.",
    "msty": "Msty is a desktop application for conversations with local and hosted AI models.",
    "code": "Visual Studio Code is a source-code editor with a large extension ecosystem, including optional AI coding tools.",
    "arduino": "Arduino IDE is used to write and upload code for Arduino electronics and hardware prototypes.",
    "idle": "Python IDLE is a basic editor and interactive shell for writing and running Python code.",
    "krita": "Krita is a digital painting and illustration program, sometimes used to make figures or diagrams.",
    "cura_slicer": "Ultimaker Cura is a 3D-printing slicer that prepares models for printing.",
    "vesktop": "Vesktop is an alternative Discord desktop client for chat, voice, and streaming.",
    "thunderbird": "Thunderbird is an email and calendar client.",
    "kmail": "KMail is KDE's desktop email client.",
    "evolution": "Evolution is a desktop email, calendar, and contacts client.",
    "geary": "Geary is a desktop email client.",
    "mailspring": "Mailspring is a desktop email client.",
    "claws_mail": "Claws Mail is a lightweight desktop email client.",
    "konsole": "Konsole is KDE's terminal emulator for shell commands and command-line programs.",
    "xterm": "XTerm is a terminal emulator for shell commands and command-line programs.",
    "uxterm": "UXTerm is a Unicode-enabled XTerm terminal emulator.",
    "gnome_terminal": "GNOME Terminal is a terminal emulator for shells and command-line programs.",
    "ptyxis": "Ptyxis is a GNOME terminal emulator for shells and command-line programs.",
    "kitty": "Kitty is a GPU-based terminal emulator for shells and command-line programs.",
    "alacritty": "Alacritty is a terminal emulator for shells and command-line programs.",
    "wezterm": "WezTerm is a terminal emulator and multiplexer for command-line workflows.",
    "foot": "Foot is a Wayland terminal emulator for shells and command-line programs.",
    "tilix": "Tilix is a tiling terminal emulator for command-line workflows.",
    "terminator": "Terminator is a terminal emulator with multiple terminal panes.",
    "xfce4_terminal": "Xfce Terminal is a terminal emulator for shells and command-line programs.",
    "mate_terminal": "MATE Terminal is a terminal emulator for shells and command-line programs.",
    "lxterminal": "LXTerminal is a lightweight terminal emulator for command-line programs.",
    "ghostty": "Ghostty is a terminal emulator for shells and command-line programs.",
    "contour": "Contour is a terminal emulator for command-line workflows.",
    "rio": "Rio is a terminal emulator for shells and command-line programs.",
    "lutris": "Lutris is a launcher and manager for PC games from multiple sources.",
    "balatro": "Balatro is a poker-inspired single-player video game.",
    "cookie_clicker": "Cookie Clicker is an incremental idle game.",
    "arknights_endfield": "Arknights: Endfield is an action role-playing and strategy video game.",
    "gryph2": "gryph2 is a Lutris-managed game entry; the launcher name alone does not identify its current game or activity.",
    "hoyoplay": "HoYoPlay is a launcher for games published by HoYoverse.",
    "prismlauncher": "Prism Launcher manages Minecraft instances, mods, and game launches.",
    "windscribe": "Windscribe is a VPN and network privacy application.",
    "htop": "htop is an interactive system and process monitor.",
    "barrier": "Barrier shares a keyboard and mouse between computers over a network.",
    "input_leap": "Input Leap shares a keyboard and mouse between computers over a network.",
    "protonplus": "ProtonPlus manages compatibility tools used to run games on Linux.",
    "protonup_qt": "ProtonUp-Qt installs and manages Steam Play compatibility tools.",
    "clicker": "Clicker is an auto-clicker that can repeatedly simulate mouse clicks and key presses.",
    "firefox": "Firefox is a web browser; the active page title and URL are more informative than the app name.",
    "chrome": "Google Chrome is a web browser; the active page title and URL are more informative than the app name.",
    "chromium": "Chromium is a web browser; the active page title and URL are more informative than the app name.",
    "opera": "Opera or Opera GX is a web browser; the active page title and URL are more informative than the app name.",
    "discord": "Discord is a chat, voice, and community application; brief task-related messages may be appropriate.",
    "teams": "Microsoft Teams is a school/work collaboration app for class and team channels, shared files, assignment information, meetings, and project coordination.",
    "slack": "Slack is a workplace collaboration app for team channels, direct messages, meetings, and shared work.",
    "google_chat": "Google Chat is a school/work collaboration app for direct messages, group spaces, and work coordination.",
    "mattermost": "Mattermost is a workplace collaboration and team messaging app.",
    "rocketchat": "Rocket.Chat is a team communication and collaboration platform.",
    "zulip": "Zulip is a team collaboration and threaded messaging app.",
    "steam": "Steam is a game store and launcher; its store or library is not itself evidence of goal-related work.",
    "systemsettings": "KDE System Settings configures desktop and system options; the active settings panel identifies the current task.",
    "kinfocenter": "KDE Info Center displays information about the computer's hardware, software, and system status.",
    "dolphin": "Dolphin is KDE's file manager for browsing and managing files and folders.",
    "discover": "KDE Discover is a software center for browsing and managing applications and updates.",
}

# Gecko soft-forks keep Firefox's sessionstore format and layout exactly,
# so they get the same browser metadata fields and are routed through the
# same sessionstore reader (see _GECKO_PROFILE_ROOTS for their paths).
for _gecko_fork in ("librewolf", "waterfox", "zen", "floorp"):
    APP_METADATA["browser"][_gecko_fork] = list(APP_METADATA["browser"]["firefox"])
del _gecko_fork

# Every app key defined across all APP_METADATA classes (for _canonical()).
_ALL_APP_KEYS = {key for apps in APP_METADATA.values() for key in apps}

# KWin/AT-SPI class -> the display name the app puts in its own window
# title, so "cranky-clippy — Dolphin" does not report the folder as
# "cranky-clippy".
_DESKTOP_APP_DISPLAY_NAMES = {
    "dolphin": {"dolphin", "file manager"},
    "systemsettings": {"system settings", "settings"},
    "kinfocenter": {"kinfocenter", "info center"},
    "ark": {"ark"},
    "spectacle": {"spectacle"},
    "discover": {"discover", "software center"},
    "kdeconnect": {"kde connect", "kdeconnect"},
    "partitionmanager": {"kde partition manager"},
    "kolourpaint": {"kolourpaint", "kolour paint"},
    "gwenview": {"gwenview"},
    "github-desktop": {"github desktop", "githubdesktop"},
    "nordvpn": {"nordvpn"},
}

# Same idea for game launchers: their window title often carries just the
# launcher's own name, which is not a game.
_GAME_DISPLAY_NAMES = {
    "steam": {"steam"},
    "heroic": {"heroic games launcher", "heroic"},
    "epic_games_launcher": {"epic games launcher", "epic"},
    "riot_client": {"riot client"},
    "battledotnet": {"battle.net", "battle"},
    "gog_galaxy": {"gog galaxy", "gog"},
    "ea_app": {"ea app", "ea"},
    "roblox": {"roblox"},
    "minecraft": {"minecraft launcher"},
    "moonlight": {"moonlight"},
    "lutris": {"lutris"},
    "hoyoplay": {"hoyoplay"},
    "arknights_endfield": {"arknights: endfield", "arknights endfield"},
}


# --- Firefox session store ---------------------------------------------------
#
# Snap Firefox is fenced off from AT-SPI by AppArmor, so its URL bar can't
# be read from the accessibility tree. But Firefox — and every Gecko
# soft-fork, which keep the same sessionstore format and layout — writes its
# complete session (all windows, all tabs, current URLs and titles) to
# sessionstore-backups/recovery.jsonlz4 every few seconds, and that file is
# world-readable for the user's own uid. That is the URL source for the
# Gecko family — no accessibility involved. Paths below cover deb/rpm,
# snap and flatpak installs (flatpak dirs also match by id glob).

_GECKO_PROFILE_ROOTS = {
    "firefox": (
        "~/.mozilla/firefox",
        "~/snap/firefox/common/.mozilla/firefox",
        "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
    ),
    "librewolf": (
        "~/.librewolf",
        "~/snap/librewolf/common/.librewolf",
        "~/.var/app/io.gitlab.librewolf-community/.librewolf",
    ),
    "waterfox": (
        "~/.waterfox",
        "~/.var/app/*waterfox*/.waterfox",
    ),
    "zen": (
        "~/.zen",
        "~/.var/app/app.zenbrowser.ZenBrowser/.zen",
    ),
    "floorp": (
        "~/.floorp",
        "~/snap/floorp/common/.floorp",
        "~/.var/app/one.ablaze.floorp/.floorp",
    ),
}

# Every gecko-family browser key routed through the sessionstore reader.
_GECKO_SESSIONSTORE_BROWSERS = set(_GECKO_PROFILE_ROOTS)


# --- Chromium-family history fallback ----------------------------------------
#
# Chrome/Chromium/Brave/Edge/Opera (and Opera GX) do not expose their UI
# through AT-SPI on some Wayland sessions — the browser frame shows up as a
# stub with no children. They do, however, keep a plain SQLite History
# database that is updated while browsing, so the current page can be found
# there: match the window title (page title) against the most recent
# visited rows. Read-only against a temp copy so the live database lock
# never matters.

# Chromium-family History fallback per browser, across packaging forms
# (deb/rpm direct config, flatpak ~/.var/app, snap ~/snap/<name>). Some
# roots may contain glob chars; each root may either hold the profile's
# History DB directly (Opera) or hold profile subdirectories that do
# (Chrome's Default/, Profile 1/...).

_CHROMIUM_PROFILE_ROOTS = {
    "chrome": (
        "~/.config/google-chrome",
        "~/.var/app/com.google.Chrome/config/google-chrome",
    ),
    "chromium": (
        "~/.config/chromium",
        "~/snap/chromium/common/chromium",
        "~/.var/app/org.chromium.Chromium/config/chromium",
    ),
    "brave": (
        "~/.config/BraveSoftware/Brave-Browser",
        "~/snap/brave/current/.config/BraveSoftware/Brave-Browser",
        "~/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser",
    ),
    "edge": (
        "~/.config/microsoft-edge",
        "~/.var/app/com.microsoft.Edge/config/microsoft-edge",
    ),
    "opera": (
        "~/.config/opera",
        "~/.config/opera-gx",
        "~/snap/opera/common/.config/opera",
        "~/.var/app/com.opera.Opera/config/opera",
        "~/.var/app/com.opera.OperaGX/config/opera-gx",
    ),
    "vivaldi": (
        "~/.config/vivaldi",
        "~/.var/app/com.vivaldi.Vivaldi/config/vivaldi",
    ),
}

# Profile directories that never contain a user's browsing history.
_PROFILE_DIR_SKIPS = {
    "system profile", "guest profile", "crashpad", "registration",
    "component updater", "crash reports", "pending pings", "profile groups",
}


def _canonical(raw):
    """Reduce an app id to an APP_METADATA key.

    Handles the messy ids desktops hand out: "firefox_firefox" (snap),
    "org.mozilla.firefox" (flatpak), "google-chrome-stable", "vscode"...
    """
    raw = (raw or "").strip().lower()
    if raw in APP_ALIASES:
        return APP_ALIASES[raw]
    if raw in _ALL_APP_KEYS:
        return raw
    # snap/flatpak/deb-style ids: find a token that names a known app
    for token in re.split(r"[-_. ]", raw):
        if not token:
            continue
        if token in APP_ALIASES:
            return APP_ALIASES[token]
        if token in _ALL_APP_KEYS:
            return token
    return raw


def _title_suffix_re(suffix):
    """RegExp for a title suffix after ' - ', ' — ' or ' – ' (KDE, Firefox
    and friends use em dashes, most Chromium windows use plain hyphens)."""
    return re.compile(r"\s+[-\u2013\u2014]\s+" + re.escape(suffix) + r"\s*$", re.I)


def _tab_title_from_window(window_title):
    """Strip the browser/identity suffix from a window title.

    Window titles look like "<tab title> - Chromium" or
    "<file path> - <project> - Visual Studio Code"; drop the LAST known
    suffix and return what's left (the active tab's title).
    """
    if not window_title:
        return None
    for suffix, _ in TITLE_SUFFIXES.items():
        m = _title_suffix_re(suffix).search(window_title)
        if m:
            return window_title[: m.start()].strip() or None
    return window_title.strip() or None


def _match_app(app_name, window_title):
    """Map the raw app id / window title to (class, app key)."""
    raw = _canonical(app_name).strip().lower()
    for cls, apps in APP_METADATA.items():
        if raw in apps:
            return cls, raw
    alias = APP_ALIASES.get(raw, raw)
    if alias != raw:
        for cls, apps in APP_METADATA.items():
            if alias in apps:
                return cls, alias
    # Some Wine/Lutris games expose a generic process class but put the
    # launcher/game name in the window caption.
    title = (window_title or "").strip().lower()
    for game_key, names in _GAME_DISPLAY_NAMES.items():
        if title in names or any(_title_suffix_re(name).search(title) for name in names):
            return "game", game_key
    # fall back to window-title suffixes (always names a known app)
    for suffix, key in TITLE_SUFFIXES.items():
        if _title_suffix_re(suffix).search(window_title or ""):
            for cls, apps in APP_METADATA.items():
                if key in apps:
                    return cls, key
    return None, None


def _match_webapp(domain):
    """Match a site domain to WEBAPP_METADATA; ('youtube_music' etc. handled)."""
    if not domain:
        return None
    # YouTube Music must be checked before the youtube.com suffix match
    if domain == "music.youtube.com" or domain.endswith(".music.youtube.com"):
        return "youtube_music"
    matches = [
        key for key in WEBAPP_METADATA
        if key != "_default" and (domain == key or domain.endswith("." + key))
    ]
    # Prefer the most specific host (e.g. outlook.office.com over office.com).
    return max(matches, key=len) if matches else "_default"


# When the URL isn't available (snap Firefox hides its URL bar behind
# AppArmor), many sites still identify themselves by their title suffix.
_WEBAPP_TITLE_HINTS = (
    (r"\s+[-\u2013\u2014]\s+YouTube Music$", "youtube_music"),
    (r"\s+[-\u2013\u2014]\s+YouTube$", "youtube.com"),
    (r"\s+\|\s+Netflix$", "netflix.com"),
    (r"\s+\|\s+Disney\+$", "disneyplus.com"),
    (r"\s+\|\s+Spotify", "spotify.com"),
    (r"\s+[-\u2013\u2014]\s+Twitch$", "twitch.tv"),
    (r"\s+[-\u2013\u2014]\s+Reddit$", "reddit.com"),
    (r"^Reddit\s+[-\u2013\u2014]\s+", "reddit.com"),
    (r"\s+[-\u2013\u2014]\s+Google Docs$", "docs.google.com"),
    (r"[\s|]+\s*Notion.?$", "notion.so"),
    (r"\s+[-\u2013\u2014]\s+Overleaf, Online LaTeX Editor", "overleaf.com"),
    (r"\s+[-\u2013\u2014|]\s+Gmail$", "mail.google.com"),
    (r"\s+[-\u2013\u2014|]\s+Outlook(?:\s+Web)?$", "outlook.office.com"),
    (r"\s+[-\u2013\u2014|]\s+Yahoo Mail$", "mail.yahoo.com"),
    (r"\s+[-\u2013\u2014|]\s+Proton Mail$", "mail.proton.me"),
    (r"\s+[-\u2013\u2014|]\s+Fastmail$", "app.fastmail.com"),
    (r"\s+[-\u2013\u2014|]\s+Zoho Mail$", "mail.zoho.com"),
    (r"\s+[-\u2013\u2014|]\s+AOL Mail$", "mail.aol.com"),
    (r"\s+[-\u2013\u2014|]\s+ChatGPT$", "chatgpt.com"),
    (r"\s+[-\u2013\u2014|]\s+Claude$", "claude.ai"),
    (r"\s+[-\u2013\u2014|]\s+DeepSeek$", "chat.deepseek.com"),
    (r"\s+[-\u2013\u2014|]\s+Gemini$", "gemini.google.com"),
    (r"\s+[-\u2013\u2014|]\s+Copilot$", "copilot.microsoft.com"),
    (r"\s+[-\u2013\u2014|]\s+Perplexity$", "perplexity.ai"),
    (r"\s+[-\u2013\u2014|]\s+Grok$", "grok.com"),
    (r"\s+[-\u2013\u2014|]\s+Mistral Le Chat$", "chat.mistral.ai"),
    (r"\s+[-\u2013\u2014|]\s+Poe$", "poe.com"),
    (r"\s+[-\u2013\u2014|]\s+Qwen Chat$", "chat.qwen.ai"),
    (r"\s+[-\u2013\u2014|]\s+Meta AI$", "meta.ai"),
    (r"\s+[-\u2013\u2014|]\s+Kimi$", "kimi.com"),
    (r"\s+[-\u2013\u2014|]\s+Z.ai Chat$", "chat.z.ai"),
    (r"\s+[-\u2013\u2014|]\s+You.com$", "you.com"),
    (r"\s+[-\u2013\u2014|]\s+Character\.AI$", "character.ai"),
)


def _match_webapp_from_title(tab_title):
    """Guess the webapp from a known site title suffix; None when unknown."""
    if not tab_title:
        return None
    for pat, key in _WEBAPP_TITLE_HINTS:
        if re.search(pat, tab_title, re.I):
            return key
    return None
