# coding: utf-8
from __future__ import unicode_literals

import re

from .common import InfoExtractor
from ..utils import (
    clean_html,
    determine_ext,
    encode_dict,
    sanitized_Request,
    ExtractorError,
    urlencode_postdata
)


class FunimationIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?funimation\.com/shows/[^/]+/videos/(?:official|promotional)/(?P<id>[^/?#&]+)'

    _TESTS = [{
        'url': 'http://www.funimation.com/shows/air/videos/official/breeze',
        'info_dict': {
            'id': '658',
            'display_id': 'breeze',
            'ext': 'mp4',
            'title': 'Air - 1 - Breeze',
            'description': 'md5:1769f43cd5fc130ace8fd87232207892',
            'thumbnail': 're:https?://.*\.jpg',
        },
    }, {
        'url': 'http://www.funimation.com/shows/hacksign/videos/official/role-play',
        'info_dict': {
            'id': '31128',
            'display_id': 'role-play',
            'ext': 'mp4',
            'title': '.hack//SIGN - 1 - Role Play',
            'description': 'md5:b602bdc15eef4c9bbb201bb6e6a4a2dd',
            'thumbnail': 're:https?://.*\.jpg',
        },
    }, {
        'url': 'http://www.funimation.com/shows/attack-on-titan-junior-high/videos/promotional/broadcast-dub-preview',
        'only_matching': True,
    }]

    def _login(self):
        (username, password) = self._get_login_info()
        if username is None:
            return
        data = urlencode_postdata(encode_dict({
            'email_field': username,
            'password_field': password,
        }))
        login_request = sanitized_Request('http://www.funimation.com/login', data, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 5.2; WOW64; rv:42.0) Gecko/20100101 Firefox/42.0',
            'Content-Type': 'application/x-www-form-urlencoded'
        })
        login = self._download_webpage(
            login_request, None, 'Logging in as %s' % username)
        if re.search(r'<meta property="og:url" content="http://www.funimation.com/login"/>', login) is not None:
            raise ExtractorError('Unable to login, wrong username or password.', expected=True)

    def _real_initialize(self):
        self._login()

    def _real_extract(self, url):
        display_id = self._match_id(url)

        errors = []
        formats = []

        ERRORS_MAP = {
            'ERROR_MATURE_CONTENT_LOGGED_IN': 'matureContentLoggedIn',
            'ERROR_MATURE_CONTENT_LOGGED_OUT': 'matureContentLoggedOut',
            'ERROR_SUBSCRIPTION_LOGGED_OUT': 'subscriptionLoggedOut',
            'ERROR_VIDEO_EXPIRED': 'videoExpired',
            'ERROR_TERRITORY_UNAVAILABLE': 'territoryUnavailable',
            'SVODBASIC_SUBSCRIPTION_IN_PLAYER': 'basicSubscription',
            'SVODNON_SUBSCRIPTION_IN_PLAYER': 'nonSubscription',
            'ERROR_PLAYER_NOT_RESPONDING': 'playerNotResponding',
            'ERROR_UNABLE_TO_CONNECT_TO_CDN': 'unableToConnectToCDN',
            'ERROR_STREAM_NOT_FOUND': 'streamNotFound',
        }

        USER_AGENTS = (
            # PC UA is served with m3u8 that provides some bonus lower quality formats
            ('pc', 'Mozilla/5.0 (Windows NT 5.2; WOW64; rv:42.0) Gecko/20100101 Firefox/42.0'),
            # Mobile UA allows to extract direct links and also does not fail when
            # PC UA fails with hulu error (e.g.
            # http://www.funimation.com/shows/hacksign/videos/official/role-play)
            ('mobile', 'Mozilla/5.0 (Linux; Android 4.4.2; Nexus 4 Build/KOT49H) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/34.0.1847.114 Mobile Safari/537.36'),
        )

        for kind, user_agent in USER_AGENTS:
            request = sanitized_Request(url)
            request.add_header('User-Agent', user_agent)
            webpage = self._download_webpage(
                request, display_id, 'Downloading %s webpage' % kind)

            playlist = self._parse_json(
                self._search_regex(
                    r'var\s+playersData\s*=\s*(\[.+?\]);\n',
                    webpage, 'players data'),
                display_id)[0]['playlist']

            items = next(item['items'] for item in playlist if item.get('items'))
            item = next(item for item in items if item.get('itemAK') == display_id)

            error_messages = {}
            video_error_messages = self._search_regex(
                r'var\s+videoErrorMessages\s*=\s*({.+?});\n',
                webpage, 'error messages', default=None)
            if video_error_messages:
                error_messages_json = self._parse_json(video_error_messages, display_id, fatal=False)
                if error_messages_json:
                    for _, error in error_messages_json.items():
                        type_ = error.get('type')
                        description = error.get('description')
                        content = error.get('content')
                        if type_ == 'text' and description and content:
                            error_message = ERRORS_MAP.get(description)
                            if error_message:
                                error_messages[error_message] = content

            for video in item.get('videoSet', []):
                auth_token = video.get('authToken')
                if not auth_token:
                    continue
                funimation_id = video.get('FUNImationID') or video.get('videoId')
                preference = 1 if video.get('languageMode') == 'dub' else 0
                if not auth_token.startswith('?'):
                    auth_token = '?%s' % auth_token
                for quality in ('sd', 'hd', 'hd1080'):
                    format_url = video.get('%sUrl' % quality)
                    if not format_url:
                        continue
                    if not format_url.startswith(('http', '//')):
                        errors.append(format_url)
                        continue
                    if determine_ext(format_url) == 'm3u8':
                        m3u8_formats = self._extract_m3u8_formats(
                            format_url + auth_token, display_id, 'mp4', entry_protocol='m3u8_native',
                            preference=preference, m3u8_id=funimation_id or 'hls', fatal=False)
                        if m3u8_formats:
                            formats.extend(m3u8_formats)
                    else:
                        f = {
                            'url': format_url + auth_token,
                            'format_id': funimation_id,
                            'preference': preference,
                        }
                        mobj = re.search(r'(?P<height>\d+)-(?P<tbr>\d+)[Kk]', format_url)
                        if mobj:
                            f.update({
                                'height': int(mobj.group('height')),
                                'tbr': int(mobj.group('tbr')),
                            })
                        formats.append(f)

        if not formats and errors:
            raise ExtractorError(
                '%s returned error: %s'
                % (self.IE_NAME, clean_html(error_messages.get(errors[0], errors[0]))),
                expected=True)

        self._sort_formats(formats)

        title = item['title']
        artist = item.get('artist')
        if artist:
            title = '%s - %s' % (artist, title)
        description = self._og_search_description(webpage) or item.get('description')
        thumbnail = self._og_search_thumbnail(webpage) or item.get('posterUrl')
        video_id = item.get('itemId') or display_id

        return {
            'id': video_id,
            'display_id': display_id,
            'title': title,
            'description': description,
            'thumbnail': thumbnail,
            'formats': formats,
        }
