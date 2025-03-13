import re
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Sample inputs
sample_date_input = '''
{
"@context": "https://schema.org",
"@type": "VideoObject",
"name": "Curious sister",
"description": "Curious sister",
"thumbnailUrl": ["https://cdn77-pic.xnxx-cdn.com/videos/thumbs169xnxxll/c8/dc/08/c8dc0897d74a015c1a3a7c959f4e1019/c8dc0897d74a015c1a3a7c959f4e1019.15.jpg"],
"uploadDate": "2017-05-06T22:07:45+00:00",
"duration": "PT00H07M12S",
"contentUrl": "https://cdn77-vid-mp4.xnxx-cdn.com/LvC_-9JV3_1GRv0IJ8N6Sg==,1741919747/videos/mp4/c/8/d/xvideos.com_c8dc0897d74a015c1a3a7c959f4e1019.mp4?ui=MTkzLjEzOC4yMTguMjI1LS0vdmlkZW8tZ2ptcGhjYi9jdXJpb3VzX3Npc3Rlcg==",
"interactionStatistic": {
"@type": "InteractionCounter",
"interactionType": { "@type": "WatchAction" },
"userInteractionCount": 263839
}
}
'''

sample_image_input = '''
logged_user = false;
	var static_id_cdn = 10;
	var html5player = new HTML5Player('html5video', '30893655');
	if (html5player) {
	    html5player.setVideoTitle('STEP SISTER PORN #22');
	    html5player.setEncodedIdVideo('hdmppom52c3');
	    html5player.setSponsors(false);
	    html5player.setVideoUrlLow('https://cdn77-vid-mp4.xnxx-cdn.com/0vIIqHL7eXjsHkVe7Aib8Q==,1741919216/videos/3gp/f/8/7/xvideos.com_f8795553f3959afd4639a8887224eab7.mp4?ui=MTkzLjEzOC4yMTguMjI1LS0vdmlkZW8taWU1cDM0OS9zdGVwX3Npc3Rlcl9wb3I=');
	    html5player.setVideoUrlHigh('https://cdn77-vid-mp4.xnxx-cdn.com/mgfmk6oP3UYJ2Nx-XTs1oQ==,1741919216/videos/mp4/f/8/7/xvideos.com_f8795553f3959afd4639a8887224eab7.mp4?ui=MTkzLjEzOC4yMTguMjI1LS0vdmlkZW8taWU1cDM0OS9zdGVwX3Npc3Rlcl9wb3I=');
	    html5player.setVideoHLS('https://cdn77-vid.xnxx-cdn.com/Tq4MaDnP8TK3UUOtoaEtXw==,1741919216/videos/hls/f8/79/55/f8795553f3959afd4639a8887224eab7/hls.m3u8');
	    html5player.setThumbUrl('https://cdn77-pic.xnxx-cdn.com/videos/thumbslll/f8/79/55/f8795553f3959afd4639a8887224eab7/f8795553f3959afd4639a8887224eab7.28.jpg');
	    html5player.setThumbUrl169('https://cdn77-pic.xnxx-cdn.com/videos/thumbs169lll/f8/79/55/f8795553f3959afd4639a8887224eab7/f8795553f3959afd4639a8887224eab7.19.jpg');
	     html5player.setRelated(video_related);
	    html5player.setThumbSlide('https://cdn77-pic.xnxx-cdn.com/videos/thumbs169/f8/79/55/f8795553f3959afd4639a8887224eab7/mozaique.jpg');
	    html5player.setThumbSlideBig('https://cdn77-pic.xnxx-cdn.com/videos/thumbnails/9f/c9/78/30893655/mozaique_full.jpg');
	    html5player.setThumbSlideMinute('https://cdn77-pic.xnxx-cdn.com/videos/thumbnails/9f/c9/78/30893655/mozaiquemin_');
	    html5player.setIdCDN('10');
	    html5player.setIdCdnHLS('10');
	    html5player.setFakePlayer(false);
	    html5player.setDesktopiew(true);
	    html5player.setSeekBarColor('#286fff');
	    html5player.setUploaderName('sister4da');
	    html5player.setUseAutoplay();
	    html5player.setVideoURL('/video-ie5p349/step_sister_porn_22');
	    html5player.setStaticPath('https://static-cdn77.xnxx-cdn.com/v-1381931ab61/v3/');
	    html5player.setHttps();
	    html5player.setCanUseHttps();
   html5player.setViewData('17d339b133fa4f5bE7_Ng1sCm23dgI2FMVFOyCPzbIr-aFH8PbdgAf8hNTickCi9lKUTr7MigfsNp5svn5AQKSZt-eKTjUag5dn5G7THneuBPsYzH-_b_ah7ee8=');
	    document.getElementById('html5video').style.minHeight = '';
	    html5player.setPlayer();
   }
'''

# Updated config with \1 instead of $1
config = {
    'date': {
        'selector': "script[type='application/ld+json']",
        'postProcess': [
            {'replace': [
                {'regex': '.*"uploadDate":\s*"([^"]+)".*', 'with': r'\1'}
            ]},
            {'parseDate': '2006-01-02T15:04:05-07:00'}
        ]
    },
    'image': {
        'selector': "script:contains('setThumbUrl169')",
        'postProcess': [
            {'replace': [
                {'regex': ".*setThumbUrl169\\(['\"]([^'\"]+)['\"]\\).*", 'with': r'\1'}
            ]}
        ]
    }
}

def process_field(field, value, config):
    logger.debug(f"Initial value for '{field}': {value}")
    
    if 'postProcess' in config:
        for step in config['postProcess']:
            if 'replace' in step:
                for pair in step['replace']:
                    regex, replacement = pair['regex'], pair['with']
                    try:
                        old_value = value
                        value = re.sub(regex, replacement, value, flags=re.DOTALL)
                        if value != old_value:
                            logger.debug(f"Applied regex '{regex}' -> '{replacement}' for '{field}': {value}")
                        else:
                            logger.debug(f"Regex '{regex}' did not match for '{field}'")
                    except re.error as e:
                        logger.error(f"Regex error for '{field}': regex={regex}, error={e}")
                        value = ''
                    except AttributeError as e:
                        logger.error(f"Replace failed for '{field}': value={value}, regex={regex}, error={e}")
                        value = ''
            if 'parseDate' in step and value and value.strip():
                try:
                    value = datetime.strptime(value.strip(), step['parseDate']).strftime('%Y-%m-%d')
                    logger.debug(f"Parsed date for '{field}' with format '{step['parseDate']}': {value}")
                except (ValueError, TypeError) as e:
                    logger.debug(f"Failed to parse date for '{field}' with format '{step['parseDate']}': '{value}', error: {e}")
                    value = ''
    
    final_value = value if value else ''
    logger.debug(f"Final value for '{field}': {final_value}")
    return final_value

def test_regex_processing():
    logger.info("Testing 'date' field...")
    date_result = process_field('date', sample_date_input, config['date'])
    logger.info(f"Result for 'date': {date_result}")

    logger.info("Testing 'image' field...")
    image_result = process_field('image', sample_image_input, config['image'])
    logger.info(f"Result for 'image': {image_result}")

if __name__ == "__main__":
    test_regex_processing()
