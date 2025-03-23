
▒█▀▀▀█ █▀▄▀█ █░░█ ▀▀█▀▀ █▀▀ █▀▀ █▀▀█ █▀▀█ █▀▀█ █▀▀ 
░▀▀▀▄▄ █░▀░█ █░░█ ░░█░░ ▀▀█ █░░ █▄▄▀ █▄▄█ █░░█ █▀▀ 
▒█▄▄▄█ ▀░░░▀ ░▀▀▀ ░░▀░░ ▀▀▀ ▀▀▀ ▀░▀▀ ▀░░▀ █▀▀▀ ▀▀▀ 

# Smutscrape · _securing smut to salty pervs over CLI_ 🍆💦

A Python-based tool to scrape and download adult content from various websites straight to your preferred data store.

---

## Requirements 🧰

- Python 3.10+ 🐍
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloads
- Either [wget](https://www.gnu.org/software/wget/) or [curl](https://curl.se/) for alternative downloads
- [ffmpeg](https://ffmpeg.org/) for M3U8 stream downloads and metadata validation
- Recommended: [Conda](https://github.com/conda/conda) or [Mamba](https://github.com/mamba-org/mamba) for environment management 🐼🐍
- Only for some sites: [Selenium](https://pypi.org/project/selenium/) + [Chromedriver](https://chromedriver.chromium.org/) for JS-heavy sites, and [webdriver-manager](https://pypi.org/project/webdriver-manager/) for foolproof ChromeDriver management.

All Python dependencies are in `requirements.txt`.

---

## Installation 🛠️

1. **Clone the Repo 📂**

   ```bash
   git clone https://github.com/io-flux/smutscrape.git
   cd smutscrape
   ```

2. **Install Dependencies 🚀**

   ```bash
   # With Conda (Recommended):
   conda create -n smutscrape python=3.10.13
   conda activate smutscrape
   pip install -r requirements.txt

   # With pip:
   pip3 install -r requirements.txt
   ```

   Install additional tools:

   ```bash
   # On Ubuntu/Debian
   sudo apt-get install yt-dlp wget curl ffmpeg chromium
   # On macOS with Homebrew
   brew install yt-dlp wget curl ffmpeg google-chrome
   ```

   For Selenium (not required for all sites):

   ```bash
   # webdriver-manager is the best solution for most people:
   pip install webdriver-manager
   # ... but a manual chromedriver installation may be necessary for some setups:
   brew install chromedriver
   ```

3. **Configure `config.yaml` ⚙️**

   ```bash
   cp example-config.yaml config.yaml
   nano config.yaml
   ```

   Set up `download_destinations`, `ignored` terms, `selenium` paths, and optional `vpn` integration for secure, anonymous scraping.

4. **Make Executable ⚡️**

   ```bash
   chmod +x scrape.py
   # Optional: add a symlink for easy use from anywhere
   sudo ln -s $(realpath ./scrape.py) /usr/local/bin/scrape
   ```

---

## Usage 🚀

Run `python scrape.py` (or `scrape` if symlinked) to download adult content and save metadata in `.nfo` files.

- **No Arguments**: Get a detailed, aesthetic readout of all supported site modes on your system, dynamically generated from `./sites/` configurations. See `screenshot1.jpg` below.

  ![Screenshot](https://github.com/io-flux/smutscrape/raw/main/screenshots/screenshot1.jpg)

- **Site Identifier Only**: Run `scrape {code}` (e.g., `scrape ml`) for detailed info about that site—curated notes (where available), script limitations, available metadata, special requirements, and usage examples for each mode. See `screenshot2.jpg` below.

  ![Screenshot](https://github.com/io-flux/smutscrape/raw/main/screenshots/screenshot2.jpg)

- **Full Command**: Build commands with `scrape {code} {mode} {query}` or use a direct URL. See the table and examples below.

### Supported Sites & Modes 🌐

| code   | site                          | modes                          | metadata                       |
| ------ | ----------------------------- | ------------------------------ | ------------------------------ |
| `9v`   | **_9Vids_** †                 | search · tag                   | tags                           |
| `fphd` | **_FamilyPornHD_** †          | tag · model · search · studio  | actors · description · studios · tags |
| `fptv` | **_FamilyPorn_** †            | model · tag · search · studio  | actors · description · studios · tags |
| `fs`   | **_Family Sex_** †            | tag · search · model           | actors · description · image · studios · tags |
| `if`   | **_IncestFlix_**              | tag ‡                          | actors · image · studios · tags |
| `ig`   | **_IncestGuru_**              | tag ‡                          | actors · image · studios · tags |
| `lf`   | **_LoneFun_**                 | search                         | description · tags             |
| `ml`   | **_Motherless_** †            | search · tag · user · group · group_code | tags                           |
| `ph`   | **_PornHub_** †               | model · category · tag · studio · search · pornstar | actors · code · date · image · studios · tags |
| `sb`   | **_SpankBang_**               | model · search · tag           | actors · description · tags    |
| `tna`  | **_TNAflix_**                 | search                         | actors · date · description · studios · tags |
| `xh`   | **_xHamster_**                | model · studio · search · tag  | actors · studios · tags        |
| `xn`   | **_XNXX_** †                  | search · model · tag · studio  | actors · date · description · image · studios · tags |
| `xv`   | **_XVideos_**                 | search · studio · model · tag · playlist | actors · studios · tags        |

† _Selenium required._  
‡ _Combine terms with "&"._

### Command-Line Arguments

```bash
scrape [args] [options]
```

**Optional Arguments:**
- `-o, --overwrite` – Replace files with the same name at the download destination.
- `-n, --re_nfo` – Replace metadata in existing `.nfo` files.
- `-a, --applystate` – Add URLs to `.state` if files exist at the destination without overwriting.
- `-p, --page {page.video}` – Start scraping on the given page and video offset (e.g., `12.9` for page 12, video 9).
- `-t, --stable {path}` – Output a table of current site configurations to the specified file path.
- `-d, --debug` – Enable detailed debug logging.
- `-h, --help` – Show the help submenu.

### Argument Details

#### Stateful Operation: `--overwrite`, `--re_nfo`, `--applystate`
**_Smutscrape_** tracks every downloaded video’s URL in `./.state`, skipping videos already successfully placed in your chosen destination (local folder, SMB share, WebDAV).  
- `--applystate`: Retroactively populates `.state` with URLs of existing files at your destination, speeding up future runs by skipping known videos without re-downloading.  
- `--overwrite`: Downloads all responsive videos, ignoring `.state` and overwriting files with matching names. **Caution**: Risks overwriting distinct videos with identical titles (e.g., "Hot Scene"), especially as your collection grows and namespace collisions increase.  
- `--re_nfo`: Regenerates `.nfo` files with fresh metadata, independent of `--overwrite`. **Note**: May overwrite `.nfo` files for different videos with the same name.  
Mitigate risks by adding `name_suffix: "{unique site identifier}"` in a site’s YAML (e.g., `name_suffix: " - Motherless.com"` for Motherless’s rampant duplicates).

#### Page and Video Offset: `--page`
Use `--page {page.video}` (e.g., `13.5` for page 13, video 5) to start scraping at a specific page and video (1-based index), then continue through all subsequent videos and pages.

#### Technical Options: `--stable`, `--debug`, `--help`
- `--stable {path}`: Outputs a table of supported sites and modes, mirroring the one below but generated from `./sites/` configs, to the specified file (e.g., `sites.md`).  
- `--debug`: Enables verbose logging for troubleshooting.  
- `--help`: Shows detailed usage info.

---

### Examples 🙋

- **Pornhub: Massy Sweet’s Pornstar Page 👧**

  ```bash
  scrape ph pornstar "Massy Sweet"
  # OR
  scrape https://www.pornhub.com/pornstar/massy-sweet
  ```

- **FamilyPornHD: MissaX Videos 👒**

  ```bash
  scrape fphd studio "MissaX"
  # OR
  scrape https://familypornhd.com/category/missax/
  ```

- **Incestflix: Chloe Temple in Brother-Sister Videos, Page 4 👧👦🏼**

  ```bash
  scrape if search "Chloe Temple & BS" --start_on_page 4
  # OR
  scrape http://www.incestflix.com/tag/Chloe-Temple/and/BS/page/4
  ```

- **Lonefun: "Real Incest" Tagged Videos 🧬**

  ```bash
  scrape lf tag "real incest"
  # OR
  scrape https://lonefun.com/@real+incest
  ```

- **Motherless: One Video In Particular... (Vintage Mother/Daughter/Son) 🙊🙈**
  ```bash
  scrape https://motherless.com/2ABC9F3
  ```

---

## Metadata Magic 🪄

Metadata (e.g., titles, tags, actors) is scraped and saved in `.nfo` files for most sites, compatible with [Plex](https://plex.tv), [Jellyfin](https://github.com/jellyfin/jellyfin), or [Stash](https://github.com/stashapp) via the [nfoSceneParser](https://github.com/stashapp/CommunityScripts/tree/main/plugins/nfoSceneParser) plugin. Some sites (e.g., _FamilySex_, _XVideos_) currently offer only titles, with full metadata planned. Use `--re_nfo` to refresh `.nfo` files.

---

## Advanced Configuration ⚙️

### Download Destinations 📁

Define destinations in `config.yaml`. The first is primary, others are fallbacks:

```yaml
download_destinations:
  - type: smb
  server: "192.168.1.69"
  share: "Media"
  path: "XXX"
  username: "user"
  password: "pass"
  temporary_storage: "/tmp/smutscrape"  # Optional: local temp dir for SMB uploads
  permissions:  # Optional
    uid: 1000
    gid: 3000
    mode: "750"
  - type: local
  path: "~/.xxx"
```

Videos download to a `.part` file, validated with `ffmpeg` for completeness, then renamed and moved to the destination, preventing partial uploads.

### Filtering Content 🚫

Skip unwanted terms in `config.yaml`:

```yaml
ignored:
  - "JOI"
  - "Age Play"
  - "Psycho Thrillers"
  - "Virtual Sex"
```

### Selenium & Chromedriver 🕵️‍♂️

For JS-heavy sites or HLS streams (marked with †), Selenium with ChromeDriver is required to emulate a browser session. By default, the script uses `webdriver-manager` for seamless setup. For manual configuration (e.g., macOS):

1. **Install Chrome Binary**:

  ```bash
  wget https://storage.googleapis.com/chrome-for-testing-public/134.0.6998.88/mac-arm64/chrome-mac-arm64.zip
  unzip chrome-mac-arm64.zip
  chmod +x "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
  sudo mv "chrome-mac-arm64/Google Chrome for Testing.app" /Applications/
  ```

2. **Install Chromedriver**:

  ```bash
  wget https://storage.googleapis.com/chrome-for-testing-public/134.0.6998.88/mac-arm64/chromedriver-mac-arm64.zip
  unzip chromedriver-mac-arm64.zip
  chmod +x chromedriver-mac-arm64/chromedriver
  sudo mv chromedriver-mac-arm64/chromedriver /usr/local/bin/chromedriver
  ```

3. **Update `config.yaml`**:

  ```yaml
  selenium:
    mode: "local"
    chromedriver_path: "/usr/local/bin/chromedriver"
    chrome_binary: "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
  ```

### VPN Support 🔒

**_Smutscrape_** can be set to automatically rotate VPN exit-nodes, using most existing VPN apps that have CLI tools. In `config.yaml`, enable and configure:

```yaml
vpn:
  enabled: true
  vpn_bin: "/usr/bin/protonvpn"
  start_cmd: "{vpn_bin} connect -f"
  new_node_cmd: "{vpn_bin} connect -r"
  new_node_time: 1200  # Refresh IP every 20 minutes
```

---

## Contributing 🤝

**_Smutscrape_** welcomes contributions! Its current 2200-line monolithic design isn’t collaboration-friendly, so refactoring into a modular, Pythonic app is a priority. Meanwhile, adding site configurations—YAML files with URL schemes and CSS selectors—is a simple, valuable contribution.

Inspired by [Stash CommunityScrapers](https://github.com/stashapp/CommunityScrapers), **_Smutscrape_**’s YAML configs adapt its structure. We use CSS selectors instead of XPath (though conversion is straightforward), and metadata fields port easily. The challenge is video downloading—some sites use iframes or countermeasures—but the yt-dlp fallback often simplifies this. Adapting a CommunityScrapers site for **_Smutscrape_** is a great way to contribute. Pick a site, tweak the config, and submit a pull request!

---

## Disclaimer ⚠️

Scrape responsibly! You’re on your own. 🧠💭
