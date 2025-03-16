# Smutscrape · *just a scraper for smut, folks!* 🍆💦

A Python-based tool to scrape and download adult content from various websites straight to your preferred data store. Whether it’s videos, tags, or search results, ***smutscrape***` has you covered—discreetly and efficiently. Supports multiple download methods, advanced scraping with Selenium for tricky sites, and metadata extraction stored in `.nfo` files for media management. 😈

---

## Requirements 🧰
- Python 3.10+ 🐍
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloads
- Either [wget](https://www.gnu.org/software/wget/) or [curl](https://curl.se/) for alternative downloads
- [ffmpeg](https://ffmpeg.org/) for M3U8 stream downloads
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
     
     # With pip:**
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
   # webdriver-manager will be the best solution for most people:
   pip install webdriver-manager
   # ... but a manual chromedriver installation may be necessary for some setups:
   brew install chromedriver
   ```

3. **Configure `config.yaml` ⚙️**
   ```bash
   cp example-config.yaml config.yaml
   nano config.yaml
   ```
   Dial in your `download_destinations`, `ignored` terms, `selenium` paths, and optional `vpn` integration for more secure and anonymous scraping.

4. **Make Executable ⚡️**
   ```bash
   chmod +x scrape.py
   # Optional: add a symlink for easy use from anywhere
   sudo ln -s $(realpath ./scrape.py) /usr/local/bin/scrape
   ```

---

## Usage 🚀

Run `python scrape.py` (or `scrape` if symlinked) to download adult content and save metadata in .nfo files.

Build commands with `scrape {code} {mode} {query}` using the table below.

### Supported Sites & Modes 🌐

| code      | site                          | modes                                            | metadata                                             |
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
Metadata (e.g., titles, tags, actors) is scraped and saved in `.nfo` files for most sites, ready for use in [Plex](https://plex.tv), [Jellyfin](https://github.com/jellyfin/jellyfin) or [Stash](https://github.com/stashapp) with the [nfoSceneParser](https://github.com/stashapp/CommunityScripts/tree/main/plugins/nfoSceneParser) plugin. Note: *FamilySexVideos*, *TopRealIncestVideos*, and *XVideos* only provide titles presently, but I hope to add full metadata support on all supported sites soon. Use `--force_new_nfo` to overwrite existing `.nfo` files with fresh metadata.

---

## Advanced Configuration ⚙️

### Selenium & Chromedriver 🕵️‍♂️
For JS-heavy sites or M3U8 streams:
- Ensure `use_selenium: true` in site config.
- Used for iframe piercing or M3U8 URL extraction (`m3u8_mode: true`).
- In `config.yaml`, set `selenium.chromedriver_path` or rely on `webdriver-manager`.

### Download Destinations 📁
Pick your desired destination for scraped videos and .nfo files in `config.yaml`. Note that the first listed destination will be used, and any others serve as a fallback, e.g. if your network share goes down.

```yaml
download_destinations:
  - type: smb
    server: "192.168.1.69"
    share: "Media"
    path: "XXX"
    username: "user"
    password: "pass"
    permissions: # optional
      uid: 1000
      gid: 3000
      mode: "750"
  - type: local 
    path: "~/.xxx"
```

### Overwriting Files
- Use `--overwrite_files` or set `no_overwrite: false` in site config to overwrite videos.
- Use `--force_new_nfo` to regenerate `.nfo` files regardless of existing ones.


### Filtering Content 🚫
Skip terms with the ignored field in `config.yaml`:
```yaml
ignored:
  - "JOI"
  - "Age Play"
```

### VPN Support 🔒
Enable in `config.yaml` and configure the start_cmd and new_node_cmd commands to match your VPN of choice:
```yaml
vpn:
  enabled: true
  vpn_bin: "/usr/bin/protonvpn"
  start_cmd: "{vpn_bin} connect -f"
  new_node_cmd: "{vpn_bin} connect -r"
  new_node_time: 1200 # refresh IP/geolocation every 20 minutes
```

---

## Disclaimer ⚠️
Scrape responsibly! You’re on your own. 🧠💭
