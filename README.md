<p align="center">
  <img src="https://raw.githubusercontent.com/sa1ntsinner/sift/main/assets/sift-wordmark.png" alt="sift" width="200" />
</p>

<p align="center"><em>Steam has thousands of discounts. sift tells you which ones are worth it.</em></p>

<p align="center">
  <a href="https://sa1ntsinner.github.io/sift/"><img src="https://img.shields.io/badge/website-sift-2bff88?style=flat" alt="Website" /></a>
  &nbsp;
  <a href="https://github.com/sa1ntsinner/sift/releases/latest"><img src="https://img.shields.io/github/v/release/sa1ntsinner/sift?style=flat&color=24292f" alt="Latest release" /></a>
  &nbsp;
  <img src="https://img.shields.io/badge/Windows%20·%20macOS%20·%20Linux-24292f?style=flat" alt="Windows, macOS, Linux" />
  &nbsp;
  <a href="https://pypi.org/project/steamsift/"><img src="https://img.shields.io/pypi/v/steamsift?style=flat&color=24292f&label=pypi" alt="PyPI" /></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-24292f?style=flat" alt="MIT license" /></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/sa1ntsinner/sift/main/assets/sift.gif" alt="sift in a terminal: a list of Steam deals with a verdict on each, the filter panel and the wishlist" width="100%" />
</p>

sift is a free terminal app for Steam deals. It reads two years of Steam prices for every discount, checks how often
the game goes on sale, whether the base price was just raised, whether a big sale is days away and what your Steam
Family already owns, and gives each deal one word.

Most "record lows" on Steam come back every five or six weeks. sift tells those apart from the prices that rarely
show up, so you buy the right game at the right moment and skip the rest.

## Verdicts

| | |
|---|---|
| **HOT** | A price that rarely comes back: a rare record, the lowest in two years, or a cheaper bundle. |
| **GREAT** | A record price, but it returns every few weeks. Buy it when you will play it. |
| **OK** | An ordinary discount for this game. |
| **MEH** | It has been 12–30% cheaper, or a big Steam sale is under three weeks away. |
| **NOPE** | It has been much cheaper, or the base price went up just before the sale. |

Prices are compared in what you pay, not in percent: $15 at −60% is not a record if the game once sold for $5.

## Install

**Download** one file from the [latest release](https://github.com/sa1ntsinner/sift/releases/latest):
`sift-windows-x64.exe`, `sift-macos-arm64` or `sift-linux-x64`. Nothing else to install.

**Or with Python 3.11+**

```bash
uv tool install steamsift      # or: pipx install steamsift
sift
```

## First run

`sift` opens a three-minute setup. It can look on your computer for your Steam account and Steam Family (only Steam's
own files, nothing is sent anywhere). You paste two free keys, and sift picks them up from the clipboard as soon as you
copy them:

| | where | |
|---|---|---|
| Steam Web API key | [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey) | domain: `localhost` · confirm in the Steam mobile app |
| IsThereAnyDeal API key | [isthereanydeal.com/apps/my](https://isthereanydeal.com/apps/my/) | Register app → copy the API key · optional, but it powers the verdicts |

Steam only issues API keys to accounts that have spent at least $5 and use Steam Guard Mobile.

## Using it

The app has four tabs (Deals · Wishlist · Discover · DLC), a verdict on every row and the game's two-year sale history
next to it. Everything works from the keyboard:

| key | | key | |
|---|---|---|---|
| `↑ ↓` `j k` | move | `/` | search |
| `enter` | open in Steam | `f` | filters, saved filters, hidden games |
| `1–4` `← →` | tabs | `s` | sort |
| `x` | hide: not for me | `u` | undo |
| `i` | price history on IsThereAnyDeal | `?` | every key |

The same filters work as flags, so a search can be one line:

```bash
sift --hot -b 10              # only HOT deals under 10 in your store's currency
sift -g roguelike --deck      # roguelikes that run on the Steam Deck
sift macro add cheap -b 2 --lowest && sift cheap
sift info "hollow knight"     # price, history and verdict for one game
sift --print                  # a plain table for scripts; sift -J prints JSON
```

## Alerts

`sift notify setup telegram` (or `discord`, `ntfy`, `desktop`, `email`) sends a few cards a day: HOT prices, your own
price targets and wishlist records that are about to end. Never the whole sale.

Run it on a schedule with `sift notify enable`, keep it running with `sift watch`, or run it in the cloud with
[GitHub Actions](packaging/github-actions/sift.yml) or [Docker](compose.yaml) while your PC is off.

## What it knows

- **Your store.** Prices in the currency Steam charges you, in whichever Steam region your account is in.
- **Your Steam Family.** Shared games stay out of the list, or show with a blue mark if you want them.
- **Your library.** Owned and hidden games never show up; DLC is listed for the games you own.
- **Your taste, second.** Deals come first; your play history breaks ties and fills the Discover tab.

Everything stays on your computer: keys in the system keychain, settings in a local file. sift talks only to Steam and
IsThereAnyDeal.

## More

`sift doctor` checks keys, privacy settings, region and family. `sift config help` lists every setting.
`sift calendar` shows the Steam sales ahead. The app speaks English and Russian (`sift config set lang ru`).

---

<p align="center"><sub>MIT license · not affiliated with Valve · price history from <a href="https://isthereanydeal.com">IsThereAnyDeal</a></sub></p>
