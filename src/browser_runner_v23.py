"""Targeted browser-pagination replacement for the already installed downloader.
Only the new entry point is modified; upstream source and existing media are kept.
Network behavior must still be verified in the user's logged-in Windows browser.
"""
from __future__ import annotations
import asyncio
import importlib.util
import json
import os
import runpy
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TOOL = Path(__file__).resolve().parent
ROOT = TOOL.parent
REPORT: dict = {}

# v2.1: retain error messages, but not URLs, cookies, or local-variable dumps.
import re
import traceback
ERROR_SECRETS = []

def error_info(exc):
    text = str(exc)
    for secret in sorted(ERROR_SECRETS, key=len, reverse=True):
        if len(secret) >= 8:
            text = text.replace(secret, '<redacted>')
    text = re.sub(r'https?://[^\s<>"\']+', '<URL>', text)
    text = re.sub(r'(?i)((?:cookie|authorization|token|sessionid|sid_guard|mstoken|uifid)\s*[:=]\s*)[^\s,;]+',
                  r'\1<redacted>', text)
    frames = traceback.extract_tb(exc.__traceback__)
    return {'type': type(exc).__name__, 'message': text[:2000],
            'stage': REPORT.get('stage', 'unknown'),
            'frames': [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                       for f in frames[-8:]]}

async def safe_evaluate(page, script, arg=None):
    markers = ('execution context was destroyed', 'cannot find context with specified id',
               'cannot find context with id', 'frame was detached',
               'cannot find default execution context')
    for attempt in range(3):
        try:
            return await page.evaluate(script, arg)
        except Exception as exc:
            temporary = any(m in str(exc).lower() for m in markers)
            if not temporary or page.is_closed() or attempt == 2:
                raise
            REPORT.setdefault('navigation_retries', []).append(error_info(exc))
            print('[RETRY] Page navigated while being read; retrying after a brief wait.', flush=True)
            await asyncio.sleep(1)

PAGE_STATE_JS = r"""() => ({
  host: location.hostname, path: location.pathname, ready: document.readyState,
  media_links: [...document.querySelectorAll('a[href]')].filter(a =>
    /(?:\/(?:video|note)\/|modal_id=)\d{15,20}/.test(a.getAttribute('href')||'')).length
})"""

async def prepare_page(page, sec_uid, items):
    REPORT['stage'] = 'reload_author_page'
    await page.goto(f'https://www.douyin.com/user/{sec_uid}',
                    wait_until='domcontentloaded', timeout=60000)
    REPORT['stage'] = 'wait_for_author_page'
    for _ in range(30):
        if page.is_closed():
            raise RuntimeError('The controlled browser page is closed.')
        view = await safe_evaluate(page, PAGE_STATE_JS)
        REPORT['page_state'] = view
        correct = view['host'] == 'www.douyin.com' and view['path'].rstrip('/') == f'/user/{sec_uid}'
        if correct and view['ready'] != 'loading' and (items or view['media_links'] > 0):
            print(f"[READY] profile page; media links={view['media_links']}; accepted posts={len(items)}", flush=True)
            return
        await asyncio.sleep(1)
    raise RuntimeError('Author page readiness not confirmed: no matching post data or media links. '
                       'Inspect page_state and post_responses_seen; login/verification may still be pending.')

SCROLL_JS = r'''(ids) => {
  const known = new Set(ids);
  const links = [...document.querySelectorAll('a[href]')].filter(a => {
    const m = (a.getAttribute('href') || '').match(/(?:\/(?:video|note)\/|modal_id=)(\d{15,20})/);
    return m && known.has(m[1]) && a.getBoundingClientRect().width > 0;
  });
  const last = links[links.length - 1];
  let target = null;
  for (let e = last; e; e = e.parentElement) {
    if (e.clientHeight > 180 && e.scrollHeight > e.clientHeight + 8 &&
        /auto|scroll/.test(getComputedStyle(e).overflowY)) { target = e; break; }
  }
  if (!target) {
    const candidates = [...document.querySelectorAll('main,section,div')].filter(e => {
      const r = e.getBoundingClientRect();
      return r.width > 450 && r.height > 250 && r.bottom > 0 && r.top < innerHeight &&
        e.scrollHeight > e.clientHeight + 8 && /auto|scroll/.test(getComputedStyle(e).overflowY);
    });
    candidates.sort((a,b) => {
      const score = e => links.filter(a => e.contains(a)).length * 1000000 + e.clientWidth*e.clientHeight;
      return score(b) - score(a);
    });
    target = candidates[0] || document.scrollingElement || document.documentElement;
  }
  const before = target.scrollTop;
  target.scrollTop = before + Math.max(650, target.clientHeight * 0.8);
  const r = target.getBoundingClientRect();
  const x = Math.min(innerWidth - 50, Math.max(50, (Math.max(0,r.left)+Math.min(innerWidth,r.right))/2));
  const y = Math.min(innerHeight - 60, Math.max(100, (Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2));
  return {x,y, before:Math.round(before), moved:Math.round(target.scrollTop-before),
    top:Math.round(target.scrollTop), height:target.scrollHeight,
    viewport:target.clientHeight, known_links:links.length,
    bottom:target.scrollHeight-target.scrollTop-target.clientHeight < 12};
}'''

def parse_post_page(payload: object, url: str, sec_uid: str):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if (parsed.hostname not in {'www.douyin.com', 'www-hj.douyin.com'} or
        parsed.path != '/aweme/v1/web/aweme/post/' or
        query.get('sec_user_id', [''])[0] != sec_uid):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get('aweme_list')
    if not isinstance(raw, list):
        raw = []
    items = []
    rejected = 0
    for item in raw:
        if not isinstance(item, dict) or not str(item.get('aweme_id') or '').isdigit():
            continue
        author = item.get('author') or {}
        owner = str(author.get('sec_uid') or '') if isinstance(author, dict) else ''
        if owner and owner != sec_uid:
            rejected += 1
            continue
        items.append(item)
    code = payload.get('status_code')
    if code not in (None, 0, '0'):
        items = []
    more = payload.get('has_more')
    more = int(more) if more in (0, 1, '0', '1', False, True) else None
    return items, {
        'response_host': parsed.hostname,
        'request_cursor': str(query.get('max_cursor', [''])[0])[:32],
        'next_cursor': str(payload.get('max_cursor', ''))[:32],
        'has_more': more, 'status_code': code if isinstance(code, (int, str)) else None,
        'received': len(raw), 'accepted': len(items), 'excluded_other_author': rejected,
    }

async def collect(self, sec_uid: str, *, expected_count=0, headless=False,
                  max_scrolls=240, idle_rounds=8, wait_timeout_seconds=600):
    from playwright.async_api import async_playwright
    global REPORT
    REPORT = {'version': '2.3', 'author_sec_uid': sec_uid, 'pages': [],
              'stop_reason': 'starting', 'coverage_verified': False, 'post_responses_seen': 0}
    ERROR_SECRETS[:] = [str(v) for v in self.cookies.values() if v]
    items: dict = {}
    pending: set = set()
    last_more = None
    state = TOOL / 'laobai-browser-state-v2.json'
    deadline = time.monotonic() + max(120, int(wait_timeout_seconds))
    self._browser_post_aweme_items = {}
    self._browser_post_stats = {}

    async def handle(response):
        nonlocal last_more
        try:
            payload = await asyncio.wait_for(response.json(), 30) if response.status == 200 else {}
            result = parse_post_page(payload, response.url, sec_uid)
            if result is None:
                return
            accepted, info = result
            info['http_status'] = response.status
            before = len(items)
            for item in accepted:
                items[str(item['aweme_id'])] = item
            info['new'] = len(items) - before
            info['total'] = len(items)
            if response.status == 200 and info['status_code'] in (None, 0, '0'):
                last_more = info['has_more']
            REPORT['pages'].append(info)
            print(f"[PAGE] host={info['response_host']} total={len(items)} new={info['new']} has_more={info['has_more']} "
                  f"cursor={info['request_cursor']} -> {info['next_cursor']} http={response.status}", flush=True)
        except Exception as exc:
            REPORT['response_error'] = error_info(exc)

    def on_response(response):
        parsed = urlparse(response.url)
        host = parsed.hostname or ''
        if (host == 'douyin.com' or host.endswith('.douyin.com')) and parsed.path.startswith('/aweme/'):
            routes = REPORT.setdefault('observed_api_routes', {})
            route = host + parsed.path
            if route in routes or len(routes) < 40:
                entry = routes.setdefault(route, {'responses': 0})
                entry['responses'] += 1
                entry['last_http_status'] = response.status
                entry['query_keys'] = sorted(parse_qs(parsed.query))

        if parsed.hostname not in {'www.douyin.com', 'www-hj.douyin.com'} or parsed.path != '/aweme/v1/web/aweme/post/':
            return
        REPORT['post_responses_seen'] += 1
        query = parse_qs(parsed.query)
        if query.get('sec_user_id', [''])[0] != sec_uid:
            REPORT['ignored_request_query_keys'] = sorted(query)
            return
        task = asyncio.create_task(handle(response))
        pending.add(task)
        task.add_done_callback(pending.discard)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                locale='zh-CN', viewport={'width':1600, 'height':900},
                storage_state=str(state) if state.exists() else None)
            try:
                if not state.exists():
                    await context.add_cookies(self._browser_cookie_payload())
                page = await context.new_page()
                context.on('response', on_response)
                try:
                    await page.goto(f'https://www.douyin.com/user/{sec_uid}',
                                    wait_until='domcontentloaded', timeout=60000)
                except Exception as exc:
                    REPORT['navigation_notice'] = error_info(exc)
                    print('[BROWSER] Navigation notice:', error_info(exc)['message'], flush=True)
                print('\n[BROWSER FIX] 请确认弹出的网页已登录，并显示目标作者的“作品”页。', flush=True)
                await asyncio.to_thread(input, '有验证码请正常完成；确认后回本终端按 Enter 开始自动翻页：')
                for candidate in reversed(context.pages):
                    if not candidate.is_closed() and urlparse(candidate.url).path.rstrip('/') == f'/user/{sec_uid}':
                        page = candidate
                        break
                await prepare_page(page, sec_uid, items)
                deadline = time.monotonic() + max(120, int(wait_timeout_seconds))
                idle = 0
                rescue_used = False
                REPORT['stop_reason'] = 'scroll_limit'
                for turn in range(max(1, int(max_scrolls))):
                    if page.is_closed():
                        REPORT['stop_reason'] = 'browser_closed'; break
                    if time.monotonic() >= deadline:
                        REPORT['stop_reason'] = 'time_budget'; break
                    before = len(items)
                    REPORT['stage'] = 'scroll_evaluate'
                    geometry = await safe_evaluate(page, SCROLL_JS, list(items))
                    REPORT['stage'] = 'scroll_mouse'
                    await page.mouse.move(geometry['x'], geometry['y'])
                    await page.mouse.wheel(0, 850)
                    await asyncio.sleep(1.8)
                    idle = idle + 1 if len(items) == before else 0
                    REPORT['last_scroll'] = geometry
                    if turn % 5 == 0:
                        print(f"[SCROLL] round={turn+1} collected={len(items)} idle={idle} "
                              f"top={geometry['before']}->{geometry['top']} height={geometry['height']} "
                              f"bottom={geometry['bottom']} has_more={last_more}", flush=True)
                    if expected_count > 0 and len(items) >= expected_count:
                        REPORT['stop_reason'] = 'configured_limit'; break
                    if last_more == 0 and idle >= 8 and geometry['bottom']:
                        REPORT['stop_reason'] = 'web_reported_end'; break
                    if idle >= max(30, int(idle_rounds)):
                        if not rescue_used:
                            print('\n[PAUSED] 网页没有继续返回新作品；请检查登录、验证码和作品列表。', flush=True)
                            answer = await asyncio.to_thread(input, '可在网页正常向下滚动，再按 Enter 重试一次；输入 s 保存当前结果并结束：')
                            if answer.strip().lower() == 's':
                                REPORT['stop_reason'] = 'user_stop'; break
                            rescue_used = True
                            idle = 0
                        else:
                            REPORT['stop_reason'] = 'stalled'; break
            finally:
                if pending:
                    await asyncio.gather(*list(pending), return_exceptions=True)
                try:
                    await context.storage_state(path=str(state))
                    self._sync_browser_cookies(await context.cookies('https://www.douyin.com'))
                except Exception as exc:
                    REPORT['state_save_error'] = type(exc).__name__
                await asyncio.gather(context.close(), return_exceptions=True)
                await asyncio.gather(browser.close(), return_exceptions=True)
    except Exception as exc:
        REPORT['stop_reason'] = 'browser_error'
        REPORT['error_type'] = type(exc).__name__
        REPORT['error'] = error_info(exc)
        print('[BROWSER ERROR]', json.dumps(REPORT['error'], ensure_ascii=False), flush=True)
    finally:
        REPORT['collected'] = len(items)
        REPORT['last_has_more'] = last_more
        REPORT['work_ids'] = list(items)
        (ROOT / 'browser-diagnostic-v23.json').write_text(
            json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
        self._browser_post_aweme_items = items
        self._browser_post_stats = {'merged_ids':len(items), 'post_api_ids':len(items),
            'selected_ids':len(items), 'post_items':len(items), 'post_pages':len(REPORT['pages'])}
        print(f"[BROWSER RESULT] collected={len(items)} stop={REPORT['stop_reason']} "
              f"last_has_more={last_more}; full-account coverage is NOT verified.", flush=True)
    return list(items)

def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(TOOL / 'browsers')
    os.environ['PYTHONUTF8'] = '1'
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    spec = importlib.util.spec_from_file_location('laobai_original', TOOL / 'download-laobai.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    if not (original.SRC / 'run.py').is_file():
        raise RuntimeError('Original downloader source is missing.')
    sys.path.insert(0, str(original.SRC))
    import yaml
    from core.api_client import DouyinAPIClient
    DouyinAPIClient.collect_user_post_ids_via_browser = collect
    config = TOOL / 'laobai-browser-v23.yml'
    settings = original.make_config()
    state_path = TOOL / 'laobai-browser-state-v2.json'
    if state_path.exists():
        saved = json.loads(state_path.read_text(encoding='utf-8'))
        for cookie in saved.get('cookies', []):
            domain = str(cookie.get('domain') or '').lstrip('.')
            if domain == 'douyin.com' or domain.endswith('.douyin.com'):
                expires = cookie.get('expires', -1)
                if expires == -1 or (isinstance(expires, (int, float)) and expires > time.time()):
                    settings['cookies'][cookie['name']] = cookie['value']
    config.write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print('[BROWSER FIX v2.3] Reusing existing media; original scripts are unchanged.', flush=True)
    sys.argv = ['run.py', '-c', str(config), '--show-warnings']
    code = 0
    try:
        runpy.run_path(str(original.SRC / 'run.py'), run_name='__main__')
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (1 if exc.code else 0)
    finally:
        result = original.audit(original.MEDIA, ROOT, code)
        print('Browser diagnostic:', ROOT / 'browser-diagnostic-v23.json', flush=True)
    if not REPORT or REPORT.get('stop_reason') != 'web_reported_end':
        print('[INCOMPLETE / UNVERIFIED] Pagination did not reach a confirmed web endpoint.', flush=True)
        return code or 3
    if REPORT.get('collected', 0) <= 0:
        print('[INCOMPLETE / UNVERIFIED] No profile posts were collected.', flush=True)
        return code or 3
    if result['empty_video_files'] or result['videos_missing_covers'] or not result['local_video_files']:
        return code or 3
    return code

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nStopped; existing files have been kept.', flush=True)
        raise SystemExit(130)
    except Exception as exc:
        print('ERROR:', type(exc).__name__, str(exc), file=sys.stderr)
        raise SystemExit(1)
