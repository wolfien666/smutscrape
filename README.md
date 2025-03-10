# Just a scraper for smut, folks. 🍆💦

A Python-based scraper for downloading adult content from various websites to your data store of choice. 😈

## Requirements 🧰
-  [yt-dlp](https://github.com/yt-dlp/yt-dlp)
-  Python 3.10+ 🐍
-  pip 📦
-  Optional: conda 🐼
-  For Javascript-heavy sites: [Selenium](https://pypi.org/project/selenium/) with Chromedriver 🧑🏼‍💻

## Installation 🛠️
1. **Clone this repo. 📂**

```bash
git clone https://github.com/io-flux/smutscrape.git
cd smutscrape
```

2. **Install dependencies. 🚀**
 - 🐍 If using conda (recommended) :
```bash
conda create -n smutscrape python=3.10.13 
conda activate smutscrape
pip install -r requirements.txt
```

 - Otherwise:
```bash
pip3 install -r requirements.txt
```

- If you plan to scrape sites that require Javascript rendering, like Motherless, ensure you also have Selenium plus a running Chromedriver or Selenium container.

You can run a standalone Selenium Docker container with Chrome by doing something like:
```bash
docker run -d -p 4444:4444 --shm-size=2g --name selenium-chrome selenium/standalone-chrome
```

3. **Customize `config.yaml` file to your system/needs. ⚙️**
```bash
cp example-config.yaml config.yaml
nano config.yaml
```

🛠️ Pay particular attention to these sections:
 - `download_destinations` 💾
 - `ignored` 🚫
 - `vpn` 🤫
 - `chromedriver` ⚙️ (if using Selenium)
   
4. **Make script executable. 🚀**
```bash
chmod +x scrape.py
```


## Usage 🚀
### Basic Usage

```bash
cd smutscrape # if not already in the repo folder
./scrape.py {{ site abbreviation }} {{ mode }} "{{ query }}"
```

### Supported sites & scraper modes 🌐
The following sites and modes are presently supported:
- `9v`: **9vids.com**
  * `search`
  * `tag`
- `if`: **incestflix.com**
  * `search`
  * to search two terms together, search for both separated by `&`
- `lf`: **lonefun.com**
  * `search`
  * `tag`
- `ml`: **motherless.com**
  * `search`
  * `category`
  * `user`
  * `group`
- `ph`: **pornhub.com**
  * `search`
  * `category`
  * `channel`
  * `model`
  * `pornstar`
- `sb`: **spankbang.com**
  * `search`
  * `model`
  * `tag`

### Examples 🧐
#### 🦉🙋🏼‍♀️ *To download all videos from Massy Sweet's pornstar page on Pornhub:*
```bash
./scrape.py ph pornstar "Massy Sweet"
```

#### 👩‍❤️‍💋‍👨🤫 *To download all videos featuring Lily LaBeau and produced by PrimalFetish from Incestflix:*

```bash
./scrape.py if search "Lily Labeau & PrimalFetish"
```

#### 🙊🙈 To download the video "Nord Video Mom Son Daughter Family Time N4L" from Motherless:
```bash
./scrape.py https://motherless.com/2ABC9F3
```

#### 🧬❣️ *To download all videos from Lonefun's "real incest" tag results:*

```bash
./scrape.py lf tag "real incest"
```

### Direct video downloads and fallback mode 😅
Each site configuration also supports directly downloading a single video from a URL: 
```bash
./scrape.py https://spankbang.com/2ei5s/video/taboo+mom+son+bath
```

And if you provide a URL from a site that doesn't match any of the configs, it still falls back on `yt-dlp` which will work for many more (though not all) platforms:
```bash
./scrape.py https://someUnsupportedSite.com/video/12345
```

### Symlink Usage 🔗
Consider creating a symlink so you can run the `scrape` (instead of `./scrape.py`) command and don't need to first `cd /path/to/your/smutscrape/`: 

```bash
sudo ln -s $(realpath ./scrape.py) /usr/local/bin/scrape
```

👨‍👩‍👧‍👦 *Then, for example, to download all videos from the "family" tag on SpankBang:*
```bash
scrape sb tag "family"
```

## Advanced Configuration Options

### Content Filtering with Ignored Terms 🚫
The `ignored` section allows you to automatically skip videos containing specified terms in their title or tags:

```yaml
ignored:
  - "JOI"
  - "Femdom"
  - "Virtual Sex"
  - "Scat"
```

This helps filter out content you're not interested in. Add or remove terms according to your preferences.

### VPN Integration 🔒
smutscrape can be configured to work with a VPN for enhanced privacy. For example the config.yaml for integrating protonvpn might look something like:

```yaml
vpn:
    enabled: true
    vpn_bin: "/usr/bin/protonvpn-cli"
    start_cmd: "{vpn_bin} connect"
    stop_cmd: "{vpn_bin} disconnect"
    new_node_cmd: "{vpn_bin} connect --random"
    new_node_time: 300
```

This allows automated VPN connections at script start and periodic reconnects for better anonymity. Set `enabled: false` to disable.

### Flexible Download Destinations 📁
smutscrape supports multiple destination types in priority order:

```yaml
download_destinations:
  - type: smb
    server: "192.168.50.5"
    share: "Media"
    # other SMB settings...
  - type: webdav
    url: "https://example.com/webdav"
    # other WebDAV settings...
  - type: local
    path: "~/.xxx"
```

**Important**: The script will use the first configured destination that works. Remove or rearrange any destination types as needed, otherwise the script may fail trying to connect to unconfigured services.

### A note about overwriting files
Note: smutscrape will not overwrite existing files with the same name at the download destination unless `no_overwrite` is set changed and set to false or removed altogether from the configuration .yaml for the site you are scraping.

## Disclaimer ⚠️
No one is responsible for how you use it except you. Please scrape responsibly. 🧠💭
