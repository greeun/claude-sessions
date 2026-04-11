# claude-sessions

**Languages:** [English](README.md) · **한국어**

> Claude Code의 모든 로컬 세션을 터미널에서 훑고, 검색하고, 이어가고, 백업하고, 옮기세요.

`claude-sessions`는 `~/.claude/projects/` 아래에 저장된 Claude Code 세션 트랜스크립트를 통째로 인덱싱하여, `fzf` 스타일의 인터랙티브 피커와 한 묶음의 서브커맨드로 관리할 수 있게 해주는 **단일 파일 Python CLI**입니다.

**왜 필요한가?** Claude Code에 내장된 `/resume`은 **현재 폴더에서 시작된 세션만** 보여줍니다. 여러 디렉터리에서 `claude`를 번갈아 실행해온 경우 전체 대화 기록을 한눈에 보거나 다른 폴더에서 시작했던 세션으로 돌아갈 방법이 없습니다. 이 도구는 `~/.claude/projects/`를 **질의 가능한 대화 데이터베이스**로 취급해 그 문제를 해결합니다.

```
 claude-sessions v0.1.0  86/86   ↑↓ move  PgUp/PgDn page  Enter open  Space mark  Del delete  Esc quit
>
   LAST ACTIVITY     SESSION      MSGS  MESSAGE
 ● 2026-04-11 15:41  f6b0b565   [  42]  로컬 시스템에서 작업했던 모든 세션 목록을 조회하는 스킬…
   2026-04-11 15:40  125ac1ac   [ 416]  biz-plan-harness 스킬을 이용해서 "경계선지능 학습자 대안…
   2026-04-11 15:26  f6e7aced   [ 202]  생성할 콘텐츠는 경계선 학습자를 위한 것으로 수준 또는 레벨…
 📁  ~/.claude/skills
```

---

## 주요 기능

- **글로벌 세션 인덱스** — `~/.claude/projects/**/*.jsonl` 전체를 폴더 구분 없이 스캔합니다.
- **인터랙티브 피커** — 실시간 키워드 필터, 화살표 이동, 멀티 선택, 선택 즉시 이어가기.
- **본문 전체 검색** — 사용자/어시스턴트 메시지를 통째로 훑고 매칭 스니펫을 보여줍니다.
- **트랜스크립트 뷰어** — `Task` 도구로 디스패치된 **서브에이전트 대화**까지 확장해서 읽을 수 있습니다.
- **백업 / 복원** — 오래된 세션을 `tar.gz`로 묶어 아카이브하고 필요할 때 복원합니다.
- **Relocate** — A 폴더에서 Claude Code를 켰지만 실제 작업은 B 폴더에서 했을 때, 기록된 작업 폴더를 B로 재작성합니다.
- **메타데이터 캐시** — `~/.cache/claude-sessions/index.json`에 인덱스를 저장합니다. 첫 실행은 수 초, 이후 실행은 거의 즉시 (mtime/size 기반 무효화).
- **의존성 제로** — Python 표준 라이브러리만 사용합니다. `pip install`이 필요 없습니다.

---

## 설치

1. 원하는 위치에 복제하세요. 예를 들어 `~/.claude/skills/claude-sessions/`에:

    ```bash
    git clone https://github.com/greeun/claude-sessions ~/.claude/skills/claude-sessions
    ```

2. 실행 권한을 주고 `$PATH`에 심볼릭 링크를 겁니다:

    ```bash
    chmod +x ~/.claude/skills/claude-sessions/sessions.py
    mkdir -p ~/.local/bin
    ln -sf ~/.claude/skills/claude-sessions/sessions.py ~/.local/bin/claude-sessions
    ```

3. 확인:

    ```bash
    claude-sessions --version
    # claude-sessions v0.1.0
    ```

`~/.local/bin`이 `PATH`에 포함되어 있어야 합니다 (대부분의 쉘 설정은 이미 포함하고 있습니다). 이 스크립트는 Python 3.9 이상이 필요하며 서드파티 의존성이 없습니다.

### 선택: 짧은 alias

피커를 자주 연다면 쉘 설정 파일에 짧은 alias를 추가하는 것을 권장합니다. 아래 중 하나를 `~/.zshrc`, `~/.bashrc`, 또는 `~/.config/fish/config.fish`에 넣으세요:

```bash
# Bash / Zsh
alias cs='claude-sessions'

# Fish
alias cs 'claude-sessions'
```

재로드:

```bash
# Bash
source ~/.bashrc
# Zsh
source ~/.zshrc
# Fish
source ~/.config/fish/config.fish
```

이후로는 `cs`로 피커를 열고, `cs search "foo"`로 검색하고, `cs list --days 7`로 최근 일주일을 나열하는 식으로 모든 서브커맨드와 플래그가 동일하게 동작합니다.

> **참고** — `cs`라는 이름이 시스템에 이미 있을 수 있으니 `type cs`로 먼저 확인하세요. 충돌이 있다면 `csess`, `cses`, `clh` 같은 다른 이름을 고르면 됩니다.

> **안전** — `claude-sessions`는 오직 `~/.claude/projects/`와 `~/.cache/claude-sessions/` 아래만 읽고 관리합니다. 저장소 코드에는 손대지 않으며, 파괴적인 명령(`delete`, `backup --delete`, `--keep-original` 없는 `relocate`)은 항상 `-y`를 주지 않는 한 확인 프롬프트를 띄웁니다.

---

## 빠른 시작

```bash
claude-sessions                     # 인터랙티브 피커 (기본)
claude-sessions list --limit 20     # 최근 20개 세션을 표로 출력
claude-sessions list --days 7       # 최근 7일 이내 세션만
claude-sessions search "migration"  # 본문 전체 검색
claude-sessions show 125ac1ac       # 세션 트랜스크립트 출력
claude-sessions resume 125ac1ac     # 원본 폴더로 cd + claude --resume
claude-sessions stats --top 10      # 프로젝트별 세션 통계
```

### 인터랙티브 피커

`claude-sessions`를 인자 없이 실행하면 curses TUI가 뜹니다:

| 키                  | 동작                                                              |
|---------------------|-------------------------------------------------------------------|
| `↑` `↓` / `Ctrl-P/N`| 선택 이동                                                         |
| `PgUp` `PgDn`       | 페이지 단위 이동                                                  |
| `Home` `End`        | 맨 앞/맨 뒤로 점프                                                |
| *문자 입력*          | 세션 id · cwd · 첫 메시지 대상 라이브 필터                         |
| `Backspace`         | 필터 문자 삭제                                                    |
| `Ctrl-U`            | 필터 초기화                                                       |
| `Space`             | 현재 행 마크/해제 (멀티 선택)                                     |
| `Ctrl-X`            | 모든 마크 해제                                                    |
| `Del` / `Fn+Delete` | 마크된(또는 현재) 세션 삭제 — 중앙 확인 모달                      |
| `Enter`             | 세션의 원본 폴더로 `cd` 후 `claude --resume <id>` 실행            |
| `Esc`               | 종료                                                              |

`Enter`를 누르면 `claude-sessions`가 자기 프로세스를 `claude --resume <id>`로 교체 실행합니다(그 세션의 원본 작업 폴더에서). 덕분에 바로 해당 대화 안으로 들어갈 수 있습니다. Claude Code를 종료하면 원래 쉘 위치로 돌아옵니다.

---

## 명령어 레퍼런스

모든 명령은 `--help`를 지원합니다. 서브커맨드 요약:

| 명령         | 하는 일                                                                                           |
|--------------|--------------------------------------------------------------------------------------------------|
| `pick`       | 인터랙티브 피커 (서브커맨드 생략 시 기본).                                                        |
| `list`       | 최근 세션 표. 플래그: `--limit N`, `--cwd PREFIX`, `--days N`.                                    |
| `search`     | 사용자·어시스턴트 본문 전체 검색. 플래그: `-i`, `--cwd PREFIX`, `--limit N`. 쿼리는 `a\|b` 형태의 OR 지원. |
| `show`       | 세션 트랜스크립트 출력. 플래그: `--max-chars N`, `--with-subagents`.                              |
| `resume`     | `cd + claude --resume` 한 줄을 생성 (혹은 파이프 실행). 플래그: `--print-only`.                   |
| `subagents`  | 부모 세션이 디스패치한 모든 서브에이전트 트랜스크립트 목록.                                       |
| `backup`     | 오래된 세션을 하나의 `tar.gz`로 아카이브 (+ JSON manifest).                                       |
| `restore`    | 백업 아카이브 복원. 플래그: `--cwd PREFIX`, `--on-conflict skip\|overwrite\|rename`, `--dry-run`. |
| `relocate`   | 세션의 기록된 `cwd`를 재작성하고 매칭 프로젝트 디렉터리로 파일 이동.                              |
| `stats`      | 프로젝트별 세션/메시지 통계.                                                                      |

### `list` / `pick` — 세션 훑어보기

```bash
claude-sessions list --limit 30
claude-sessions pick --days 14 --cwd ~/project/acme
```

`pick`은 curses 피커, `list`는 동일한 데이터를 일반 테이블로 출력합니다 (파이프로 `grep`, `less` 등에 연결 가능).

### `search` — 본문 전체 검색

```bash
claude-sessions search "rate limiter" -i --limit 20
claude-sessions search "nextjs|remix" --cwd ~/project
```

각 히트는 세션 id, cwd, 타임스탬프와 함께 매칭 스니펫 최대 3개를 보여줍니다.

### `show` — 트랜스크립트 읽기

```bash
claude-sessions show 125ac1ac                  # 부모 세션만
claude-sessions show 125ac1ac --with-subagents # + 디스패치된 모든 서브에이전트
claude-sessions show agent-aafeba26            # 서브에이전트 id prefix로 바로 조회
```

`show`는 8글자 이상의 prefix를 받아들이며, `<parent-id>/subagents/` 아래에 저장된 서브에이전트 `agent-<hex>` id도 매칭합니다.

### `subagents` — Task 디스패치 결과 보기

```bash
claude-sessions subagents 125ac1ac
```

부모 세션이 생성한 서브에이전트 전체 목록과 각 에이전트 타입, 메시지 수, 첫 프롬프트를 표시합니다. Claude Code가 서브에이전트 트랜스크립트 옆에 남기는 `.meta.json`에서 정보를 가져옵니다.

### `resume` — 세션으로 바로 복귀

```bash
claude-sessions resume 125ac1ac            # cd + claude --resume 명령 출력
claude-sessions resume 125ac1ac --print-only | bash   # 바로 실행
```

피커의 `Enter` 키도 같은 로직을 사용합니다.

### `backup` — 오래된 세션 아카이브

```bash
claude-sessions backup --dry-run                          # 계획 미리보기
claude-sessions backup --days 90                          # 90일 이상 된 세션 아카이브
claude-sessions backup --before 2025-01-01 --delete       # 아카이브 + 원본 제거
claude-sessions backup --cwd ~/project/acme --out acme.tgz
```

- 각 세션의 `.jsonl`과 아카이브를 설명하는 `manifest.json`(`created_at`, `cutoff`, 세션별 메타데이터 포함)을 압축 tarball로 씁니다.
- 기본 출력 경로는 `~/.claude/backups/sessions-<timestamp>.tar.gz`입니다.
- `--delete`는 아카이브 성공 후에만 원본을 제거합니다. 일부 파일이 아카이브에 실패했을 때도 원본을 제거하려면 `--force`가 필요합니다.

### `restore` — 백업 풀기

```bash
claude-sessions restore ~/.claude/backups/sessions-20260411-153000.tar.gz --dry-run
claude-sessions restore <archive> --on-conflict rename
claude-sessions restore <archive> --cwd ~/project/acme
```

복원된 파일은 `~/.claude/projects/`로 되돌아가고, 캐시가 무효화되어 다음 실행 시 재인덱싱됩니다. 충돌 정책은 `skip`(기본), `overwrite`, `rename`(기존 파일은 유지하고 복원본을 `<id>.restored-<timestamp>.jsonl`로 저장)이 있습니다.

### `relocate` — 기록된 cwd 고치기

Claude Code를 A 폴더에서 켰지만 실제 작업은 B 폴더에서 한 경우(`cd`, `Bash` 도구 등으로 이동), Claude Code는 여전히 A를 세션의 작업 폴더로 기록합니다. `relocate`는 모든 이벤트의 `cwd` 필드를 재작성하고 **동시에** `.jsonl` 파일을 B의 프로젝트 디렉터리로 이동시켜, `claude --resume`과 `claude-sessions resume` 모두 올바른 위치에서 복귀하도록 합니다:

```bash
claude-sessions relocate f6b0b565 ~/project/actual-work --dry-run
claude-sessions relocate f6b0b565 ~/project/actual-work
claude-sessions relocate f6b0b565 ~/project/actual-work --keep-original
```

`<parent-id>/subagents/` 아래에 저장된 서브에이전트 트랜스크립트도 부모와 함께 이동합니다(`--keep-original`이면 복사).

### `stats` — 프로젝트별 통계

```bash
claude-sessions stats --top 15
```

총 세션/메시지 수와 세션이 가장 많은 프로젝트 폴더를 출력합니다.

---

## 동작 원리

Claude Code는 모든 세션을 다음 경로에 JSON-Lines 파일로 저장합니다:

```
~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
```

`<encoded-cwd>`는 세션의 시작 작업 폴더에서 알파벳·숫자·`-`가 아닌 모든 문자를 `-`로 치환한 결과입니다. 예를 들어 `/Users/me/.claude/skills`는 `-Users-me--claude-skills`가 됩니다. 파일의 각 줄은 JSON 이벤트(`type: user | assistant | tool_use | ...`)이며 캡처 시점의 `cwd` 필드를 포함합니다.

`Task` 도구로 디스패치된 서브에이전트는 부모 세션 옆에 저장됩니다:

```
~/.claude/projects/<cwd-dir>/<parent-id>/subagents/
  ├── agent-<hex>.jsonl       # 서브에이전트 트랜스크립트
  └── agent-<hex>.meta.json   # { agentType, description }
```

`claude-sessions`는 최상위 세션과 서브에이전트 트랜스크립트를 모두 읽습니다. 인덱스는 `~/.cache/claude-sessions/index.json`에 절대 경로, 수정 시각, 크기 기준으로 캐시되어 있으며, 변경되지 않은 파일은 바로 캐시에서 복원됩니다.

---

## 데이터 안전

- **기본 읽기 전용** — `list`, `search`, `show`, `subagents`, `stats`, `resume`, `pick`(피커의 `d`/`Del` 제외)은 어떤 파일도 수정하지 않습니다.
- **파괴적 작업에는 확인** — 피커의 `delete`는 모달 프롬프트를 사용하고, `backup --delete`, `restore`, `relocate`는 CLI에서 `-y` 없이는 확인 프롬프트를 띄웁니다.
- **Atomic 쓰기** — `relocate`는 새 파일을 `.tmp` 경로에 쓴 후 성공 시 rename으로 교체합니다. 중간에 실행이 끊겨도 반쪽짜리 세션이 남지 않습니다.
- **가역적 `backup`** — `--delete`를 명시하기 전까지 원본은 그대로 유지됩니다. 아카이브는 일반 `tar.gz`라 `tar -tzf`로 내용을 확인할 수 있습니다.
- **캐시는 일회용** — 언제든 `~/.cache/claude-sessions/index.json`을 지워도 됩니다. 다음 실행이 재구축합니다.

---

## 버전 관리

`claude-sessions --version`으로 현재 버전을 확인할 수 있고, 피커 헤더에도 표시됩니다. 릴리스를 끊을 때는 `sessions.py` 상단의 `__version__` 문자열을 갱신하세요.

현재 버전: **0.1.0**

---

## 라이선스

MIT (또는 배포에 맞는 라이선스로 — 포크하는 경우 이 섹션을 업데이트하세요).
