"""
Source updates from Mirror酱 (MirrorChyan) for the master branch of the official repository.

Mirror酱 serves every commit of the branch as a git pack: the snapshot of the commit, or only
the objects that are new since the commit the client is on. The pack goes into the repository
and the commit becomes a shallow boundary, so the repository ends up the way `git fetch` would
leave it, and git keeps working as the fallback.

Versions are named after the committer time of their commit, in UTC (%Y%m%d%H%M%S), so the
current version comes from HEAD alone. Any failure leaves HEAD and the work tree as they were.
"""

import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import Optional, Tuple

from module.logger import logger

# values of UpdateSource
SOURCE_GIT = 'git'
SOURCE_MIRRORCHYAN = 'mirrorchyan'

# Mirror酱 serves this branch of these repositories; anything else updates through git
MIRRORCHYAN_BRANCH = 'master'
OFFICIAL_REPOSITORIES = (
    'github.com/megumiss/nikkeautoscript',
    'git.megumiss.top/megumiss/nikkeautoscript',
    'gitee.com/megumiss/nikkeautoscript',
)

VERSION_NAME_FORMAT = '%Y%m%d%H%M%S'

# <ref>/<commit> points at the version an update to <commit> came from, where the
# history goes on when the commit has no parents locally; it also keeps that version
# from being pruned. Only the newest are kept: the update page shows 20 commits.
MIRRORCHYAN_PREVIOUS_REF = 'refs/mirrorchyan/previous'
HISTORY_LINKS_KEPT = 20

# where NKAS is on Mirror酱; not user settings, development points them elsewhere through
# the environment
DEFAULT_API = 'https://mirrorchyan.com/api'
DEFAULT_RID = 'NKAS'


def api_base() -> str:
    return os.environ.get('MIRRORCHYAN_API') or DEFAULT_API


def resource_id() -> str:
    return os.environ.get('MIRRORCHYAN_RID') or DEFAULT_RID


# the reasons behind the codes Mirror酱 answers a CDK problem with
CDK_ERRORS = {
    7001: 'CDK 已过期，请使用新的 CDK',
    7002: 'CDK 无效，请检查输入是否正确',
    7003: 'CDK 今日下载次数已达上限，请明日再试',
    7004: 'CDK 类型与 NKAS 不匹配，请检查 CDK 的适用范围',
    7005: 'CDK 已被封禁，可能由于退款或非正常使用',
}


class MirrorChyanError(Exception):
    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code

    @property
    def cdk_problem(self) -> bool:
        """The CDK, not Mirror酱 or the network, is what failed."""
        return self.code in CDK_ERRORS


def is_official_repository(url: str) -> bool:
    url = (url or '').strip().lower().rstrip('/')
    if url.endswith('.git'):
        url = url[:-4]
    return url.split('://', 1)[-1] in OFFICIAL_REPOSITORIES


def serves(repository: str, branch: str) -> bool:
    """Whether Mirror酱 has the updates of this repository and branch."""
    return branch == MIRRORCHYAN_BRANCH and is_official_repository(repository)


class MirrorChyan:
    def __init__(self, git: str, api: str, rid: str, cdk: str, timeout: int = 60):
        self.git = git
        self.api = api.rstrip('/')
        self.rid = rid
        self.cdk = cdk
        self.timeout = timeout

    def _git(self, *args, stdin=None) -> str:
        result = subprocess.run(
            [self.git, *args],
            stdin=stdin,
            capture_output=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', 'replace').strip()
            raise MirrorChyanError(f'git {" ".join(args)} failed: {stderr}')
        return result.stdout.decode('utf-8', 'replace').strip()

    def head(self) -> Optional[str]:
        if not os.path.exists('./.git'):
            return None
        try:
            return self._git('rev-parse', '--verify', '-q', 'HEAD^{commit}')
        except MirrorChyanError:
            return None

    def version_name(self, commit: str) -> str:
        """
        The committer time read from the commit object itself: `git log` would also load
        the parents, which a shallow boundary does not have.
        """
        for line in self._git('cat-file', 'commit', commit).splitlines():
            if not line:
                break
            if line.startswith('committer '):
                timestamp = int(line.rsplit(' ', 2)[1])
                return datetime.fromtimestamp(timestamp, timezone.utc).strftime(VERSION_NAME_FORMAT)
        raise MirrorChyanError(f'commit {commit} has no committer')

    def current_version(self) -> Tuple[Optional[str], str]:
        head = self.head()
        return head, (self.version_name(head) if head else '')

    def latest(self, current: str, with_cdk: bool = True) -> dict:
        """
        Without the CDK Mirror酱 only names the latest version, which is enough to check.
        """
        query = {
            'current_version': current,
            'channel': 'stable',
            'user_agent': 'NKAS',
        }
        if with_cdk:
            query['cdk'] = self.cdk
        url = f'{self.api}/resources/{urllib.parse.quote(self.rid)}/latest?{urllib.parse.urlencode(query)}'
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read())
            except Exception:
                raise MirrorChyanError(f'Mirror酱 returned HTTP {e.code}')
        except Exception as e:
            raise MirrorChyanError(f'cannot reach Mirror酱: {e}')
        code = payload.get('code')
        if code != 0:
            reason = CDK_ERRORS.get(code) or f'Mirror酱: {payload.get("msg") or code}'
            raise MirrorChyanError(reason, code)
        return payload.get('data') or {}

    def verify(self) -> int:
        """
        Asks with the CDK, which Mirror酱 validates.

        Returns:
            int: when the CDK expires, as a unix time; 0 if Mirror酱 does not say

        Raises:
            MirrorChyanError: with the reason Mirror酱 gives, e.g. an expired CDK
        """
        _, current = self.current_version()
        return int(self.latest(current).get('cdk_expired_time') or 0)

    # when the CDK expires, as a unix time, from the last check; 0 if unknown
    cdk_expires = 0

    def check(self) -> Optional[dict]:
        """
        Asks with the CDK, so Mirror酱 validates it and says when it expires; a
        missing incremental package gets queued then, ready for the update.

        Returns:
            dict: version_name and release_note of the version Mirror酱 has instead of
                the local one, None if it has the local one
        """
        _, current = self.current_version()
        latest = self.latest(current)
        self.cdk_expires = int(latest.get('cdk_expired_time') or 0)
        name = latest.get('version_name')
        if not name:
            raise MirrorChyanError('Mirror酱 named no version')
        # another name means another commit, older ones included: the branch may move back
        if name == current:
            return None
        return {'version_name': name, 'release_note': latest.get('release_note') or ''}

    def _download(self, data: dict, directory: str) -> Tuple[dict, str]:
        url, sha256 = data.get('url'), data.get('sha256')
        if not url or not sha256:
            raise MirrorChyanError('Mirror酱 gave no package')
        archive = os.path.join(directory, 'package.zip')
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp, open(archive, 'wb') as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                    f.write(chunk)
        except Exception as e:
            raise MirrorChyanError(f'download failed: {e}')
        if digest.hexdigest() != sha256.lower():
            raise MirrorChyanError('the package does not match its sha256')

        extracted = os.path.join(directory, 'package')
        try:
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                packs = [n for n in names if n.endswith('.pack') and '/' not in n]
                if 'meta.json' not in names or len(packs) != 1:
                    raise MirrorChyanError('the package holds no git pack')
                meta = json.loads(z.read('meta.json'))
                z.extract(packs[0], extracted)
        except zipfile.BadZipFile as e:
            raise MirrorChyanError(f'broken package: {e}')
        os.remove(archive)
        if not meta.get('commit'):
            raise MirrorChyanError('the package names no commit')
        return meta, os.path.join(extracted, packs[0])

    def fetch(self, source: str, branch: str) -> Tuple[bool, str]:
        """
        Puts the latest commit into the repository and points {source}/{branch} at it,
        as `git fetch` does; the caller checks it out.

        Returns:
            bool: whether there was another version
            str: its release note
        """
        head, current = self.current_version()
        data = self.latest(current)
        if not data.get('url'):
            if data.get('version_name') != current:
                raise MirrorChyanError('Mirror酱 gave no package')
            return False, ''
        logger.info(f'Mirror酱: {current or "none"} -> {data.get("version_name")}')

        with tempfile.TemporaryDirectory(prefix='mirrorchyan-') as directory:
            meta, pack = self._download(data, directory)
            if meta.get('base') and meta['base'] != head:
                # an incremental package only fits the commit it was built from
                logger.info('Mirror酱 package is for another commit, ask for the full one')
                data = self.latest('')
                meta, pack = self._download(data, directory)
            commit = meta['commit']

            with open(pack, 'rb') as f:
                self._git('index-pack', '--stdin', stdin=f)
            # every tree and file of the commit is there now, from the pack or from before
            self._git('rev-list', '--objects', '--no-walk', commit)

        if not self._parents_present(commit):
            # without a shallow boundary git would try to walk into the missing parents
            shallow = self._git('rev-parse', '--git-path', 'shallow')
            with open(shallow, 'ab') as f:
                f.write(commit.encode() + b'\n')
            # the history goes on from the version the update came from; not after a
            # rollback, where that version is the newer one
            if head and self.version_name(commit) >= self.version_name(head):
                self._git('update-ref', f'{MIRRORCHYAN_PREVIOUS_REF}/{commit}', head)
                self._prune_history_links()
        self._git('update-ref', f'refs/remotes/{source}/{branch}', commit)
        # each update adds a pack; nothing else here runs the automatic gc
        self._git('gc', '--auto', '--quiet')
        return True, data.get('release_note') or ''

    def _parents_present(self, commit: str) -> bool:
        """Whether the repository has every parent of the commit, as after an update to
        the version right after the local one."""
        for line in self._git('cat-file', 'commit', commit).splitlines():
            if not line:
                break
            if line.startswith('parent '):
                found = subprocess.run([self.git, 'cat-file', '-e', line[len('parent '):] + '^{commit}'],
                                       capture_output=True)
                if found.returncode != 0:
                    return False
        return True

    def _prune_history_links(self):
        links = self._git('for-each-ref', '--sort=-committerdate', '--format=%(refname)',
                          MIRRORCHYAN_PREVIOUS_REF).splitlines()
        for ref in links[HISTORY_LINKS_KEPT:]:
            self._git('update-ref', '-d', ref)
