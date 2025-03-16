# Smutscrape · *just a scraper for smut, folks!* 🍆💦

A Python-based tool to scrape and download adult content from various websites straight to your preferred data store. Whether it’s videos, tags, or search results, ***smutscrape***` has you covered—discreetly and efficiently. Supports multiple download methods, advanced scraping with Selenium for tricky sites, and metadata extraction stored in `.nfo` files for media management. 😈

---

## Requirements 🧰
- Python 3.10+ 🐍
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloads
- [wget](https://www.gnu.org/software/wget/) or [curl](https://curl.se/) for alternative downloads
- [ffmpeg](https://ffmpeg.org/) for M3U8 stream downloads
- Optional: [Selenium](https://pypi.org/project/selenium/) + [Chromedriver](https://chromedriver.chromium.org/) for JS-heavy sites
- Optional: [webdriver-manager](https://pypi.org/project/webdriver-manager/) for automatic ChromeDriver management (in `requirements.txt`)
- Optional: Conda for environment management 🐼

All Python dependencies are in `requirements.txt`.

---

## Installation 🛠️

1. **Clone the Repo 📂**
   ```bash
   git clone https://github.com/io-flux/smutscrape.git
   cd smutscrape
   ```

2. **Install Dependencies 🚀**
   - **With Conda (Recommended):**
     ```bash
     conda create -n smutscrape python=3.10.13
     conda activate smutscrape
     pip install -r requirements.txt
     ```
   - **With pip:**
     ```bash
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
   - `webdriver-manager` auto-downloads ChromeDriver by default.
   - Or install manually (e.g., `brew install chromedriver`) and set `chromedriver_path` in `config.yaml`.

3. **Configure `config.yaml` ⚙️**
   ```bash
   cp example-config.yaml config.yaml
   nano config.yaml
   ```
   Dial in your `download_destinations`, `ignored` terms, `selenium` paths, and optional `vpn` integration for more secure and anonymous scraping.

4. **Make Executable 🚀**
   ```bash
   chmod +x scrape.py
   # Optional: add a symlink for easy use from anywhere
   sudo ln -s $(realpath ./scrape.py) /usr/local/bin/scrape
   ```

---

## Usage 🚀

**Smutscrape** scrapes adult content from various websites using "modes" to target videos, searches, tags, or performer pages, with metadata saved in `.nfo` files alongside downloads.

### Supported Sites & Modes 🌐
Build commands with `scrape {Code} {Mode} {Query}` (e.g., `scrape ph pornstar "Massy Sweet"`) using the codes, modes, and metadata options below.

| Code      | Site                          | Modes                                            | Metadata                                             |
|-----------|-------------------------------|--------------------------------------------------|------------------------------------------------------|
| `9v`      | ***9vids.com***               | `video` · `search` · `tag`                       | Title · Tags                                         |
| `fphd`    | ***familypornhd.com*** †      | `video` · `category` · `tag` · `studio`          | Title · Studios · Actors · Tags · Description        |
| `fptv`    | ***familyporn.tv*** †         | `video` · `search` · `category` · `actors`       | Title · Studios · Actors · Tags · Description        |
| `fs`      | ***family-sex.me*** †         | `video` · `search` · `tag`                       | Title · Studios · Actors · Tags · Description        |
| `fsv`     | ***familysexvideos.org*** †   | `video` · `search`                               | Title                                                |
| `if`      | ***incestflix.com***          | `video` · `search`‡ · `tag`‡                     | Title · Studios · Actors · Tags · Image              |
| `lf`      | ***lonefun.com***             | `video` · `search` · `tag`                       | Title · Tags · Description                           |
| `ml`      | ***motherless.com*** †        | `video` · `search` · `category` · `user` · `group` | Title · Tags                                       |
| `ph`      | ***pornhub.com*** †           | `video` · `model` · `category` · `channel` · `search` · `pornstar` | Title · Studios · Actors · Tags · Date · Code · Image |
| `sb`      | ***spankbang.com***           | `video` · `model` · `search` · `tag`             | Title · Actors · Tags · Description                  |
| `tna`     | ***tnaflix.com***             | `video` · `search`                               | Title · Studios · Actors · Tags · Description · Date |
| `triv`    | ***toprealincestvideos.com*** | `video` · `search` · `category`                  | Title                                                |
| `xh`      | ***xhamster.com***            | `video` · `search` · `category` · `pornstar`     | Title · Studios · Actors · Tags                      |
| `xnxx`    | ***xnxx.com*** †              | `video` · `search` · `channel` · `pornstar` · `tag` · `pornmaker` | Title · Studios · Actors · Tags · Description · Date · Image |
| `xv`      | ***xvideos.com***             | `video` · `search` · `channel` · `model` · `tag` | Title                                                |

† *Selenium required.*  
‡ *Combine two search or tag queries with '&'.*

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

- **Incestflix: Chloe Temple as Sister, Page 4 👧**
  ```bash
  scrape if search "Chloe Temple & Sister" --start_on_page 4
  # OR
  scrape http://www.incestflix.com/tag/Chloe-Temple/and/Sister/page/4
  ```

- **Lonefun: "Real Incest" Tag Results 🧬❣️**
  ```bash
  scrape lf tag "real incest"
  # OR
  scrape https://lonefun.com/@real+incest
  ```

- **Motherless: Specific Video (Vintage Mother/Daughter/Son) 🙊🙈**
  ```bash
  scrape https://motherless.com/2ABC9F3
  ```

---

## Metadata Magic
Metadata (e.g., titles, tags, actors) is scraped and saved in `.nfo` files for most sites, ready for use in [Plex](https://plex.tv), [Jellyfin](https://github.com/jellyfin/jellyfin) or [Stash](https://github.com/stashapp) with the [nfoSceneParser](https://github.com/stashapp/CommunityScripts/tree/main/plugins/nfoSceneParser) plugin. Note: *FamilySexVideos*, *TopRealIncestVideos*, and *XVideos* only provide titles presently, but I hope to add full metadata support on all supported sites soon. Use `--force_new_nfo` to overwrite existing `.nfo` files with fresh metadata.

---

## Advanced Configuration ⚙️

### Selenium & Chromedriver 🕵️‍♂️
For JS-heavy sites or M3U8 streams:
- Enable with `use_selenium: true` in site config.
- Used for iframe piercing or M3U8 URL extraction (`m3u8_mode: true`).
- In `config.yaml`, set `selenium.chromedriver_path` or rely on `webdriver-manager`.

### Download Destinations 📁
Set in `config.yaml`:
```yaml
download_destinations:
  - type: "local"
    path: "~/.xxx"
```

### Overwriting Files
- Use `--overwrite_files` or set `no_overwrite: false` in site config to overwrite videos.
- Use `--force_new_nfo` to regenerate `.nfo` files regardless of existing ones.


### Filtering Content 🚫
Skip terms in `config.yaml`:
```yaml
ignored:
  - "JOI"
  - "Age Play"
```

### VPN Support 🔒
Enable in `config.yaml`:
```yaml
vpn:
  enabled: true
  vpn_bin: "/usr/bin/protonvpn-cli"
  start_cmd: "{vpn_bin} connect"
  new_node_time: 300
```

---

## Disclaimer ⚠️
Scrape responsibly! You’re on your own. 🧠💭
