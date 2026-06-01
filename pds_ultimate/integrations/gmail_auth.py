"""One-time Google OAuth setup for Gmail + Calendar.

Usage:
    python3 -m pds_ultimate.integrations.gmail_auth

Opens browser → sign in → saves token to data/gmail_token.json
"""

from __future__ import annotations

from pds_ultimate.config import config
from pds_ultimate.integrations.google_auth import GOOGLE_SCOPES, run_oauth_flow


def main() -> int:
    print("=" * 60)
    print("  Google OAuth — Gmail + Calendar")
    print("=" * 60)
    print(f"  Credentials: {config.gmail.credentials_file}")
    print(f"  Token file:  {config.gmail.token_file}")
    print(f"  Scopes:      {', '.join(GOOGLE_SCOPES)}")
    print()
    print("  Откроется браузер — войди в alexkurumbayev@gmail.com")
    print("  и разреши доступ к Gmail и Calendar.")
    print()

    ok, reason = run_oauth_flow()
    if ok:
        print("\n✅ Готово! Token сохранён. Перезапусти агента.")
        return 0
    print(f"\n❌ Ошибка: {reason}")
    if "access_denied" in reason.lower() or "403" in reason:
        print(
            "\n💡 Если видишь «Access blocked / has not completed verification»:\n"
            "   1. Открой https://console.cloud.google.com/apis/credentials/consent\n"
            "   2. Проект: project-623e3cdf-f967-472d-859\n"
            "   3. OAuth consent screen → Test users → ADD USERS\n"
            "   4. Добавь: alexkurumbayev@gmail.com → Save\n"
            "   5. Запусти этот скрипт снова"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
