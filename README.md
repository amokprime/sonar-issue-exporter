# sonar-issue-exporter

### 🚧Account flag🚧
This started around the time I migrated from Windows 11 to Fedora 44 KDE. It means:  GitHub Pages, GitHub Actions (aka CI), GitHub Copilot, are all down for me. The `git clone/git pull` based installation steps for this project are not affected. After the previous commit, I decided to only commit linting patches and documentation edits until either the flag is lifted or I redeploy CI elsewhere.

### AI Disclosure and Disclaimer
I am neither a developer nor affiliated with Sonar. The Python scripts in this repo are vibe-coded with [DeepSeek](https://chat.deepseek.com/) and [Z.ai](https://chat.z.ai/). Prompt history for the scripts is in [/archive](https://github.com/amokprime/sonar-issue-exporter/tree/main/archive). I have only tested the scripts with GitHub on Windows 11 (0.1.0-0.2.0) and Fedora 44 KDE (0.2.1+). They might also work for repos on GitLab, Bitbucket, and Azure Cloud on any OS where Python is supported.

sonar-issues-exporter is not an official Sonar product. It is a client tool that fetches data from the SonarQube Cloud [Web API](https://docs.sonarsource.com/sonarqube-cloud/appendices/web-api). Users must have their own authorized SonarCloud account and API token. Rule descriptions and educational content are the intellectual property of SonarSource SA. This tool does not bundle or redistribute SonarSource content (see .gitignore).

### About
sonar-issue-exporter is a tool for downloading SonarQube Cloud issues to text files that an AI can read. It was created to help fix maintainability issues in my other vibe-coded app (LineByLine).

### Setup

#### SonarCloud GitHub Action
1. Add a SonarCloud analysis GitHub workflow to your GitHub repo. Follow the instructions in the sonarcloud.yml template.
2. Go to your repo Settings/Rules/Rulesets → Require code scanning results and add SonarCloud. It should now scan before any commit.
3. For private projects, go to your SonarQube Cloud account → Security (shield icon) in left ribbon → Generate Tokens → Enter some name you'll remember → Copy the token and save it to a password manager like KeepassXC

#### Installation
1. Install [Python 3.10+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/getting-started/installation/)
2. Install sonar-issue-exporter:
```sh
git clone https://github.com/amokprime/sonar-issue-exporter.git
cd sonar-issue-exporter
uv tool install ".[markdown]"
```
3. Create an `.env` file in your home folder (i.e. `%USERNAME%`, `~`). For private projects, paste your token between the quotes and save. The tool searches for `.env` in the current directory, then your home folder. If `FETCH_PATH` is not set, downloaded files go to the current working directory.
```env
BEARER_TOKEN="your-token-here"
FETCH_PATH="/path/to/downloads"
```
4. Update the tool:
```sh
cd /path/to/sonar-issue-exporter
git pull
uv tool install --force --no-cache ".[markdown]"
```

### Usage

#### Clipboard watcher
1. Open a Sonar page with issues.
2. Run `sonar-watch` from a terminal
3. `Alt+Tab` back to the Sonar page. Copy each issue's link (on Firefox, right click the blue titles and press `L`, scrolling down as needed) and wait for the download to finish. Issues of the same category are automatically deduplicated into a single folder. Each category folder contains:
	1. L{line number}.json - "Where is the issue?". Possibly more than one of these.
	2. why.md - "Why is this an issue?" At most one of these.
	3. how.md - "How can I fix it?" At most one of these.
4. Close the terminal window or press `Ctrl+C` when finished.
5. Upload the folders (as a zip) and their associated app file(s) to a free AI web chat like chat.z.ai or claude.ai. Ask them to include the line affected (i.e. L303) so you can `Ctrl+F` the Sonar project Issues page. Update each unchanged (i.e. "Won't Fix", "defer until refactor") issue's status from Open to "Accept" or "False Positive". If the AI fixed an issue, leave the status Open instead of changing to "Fixed". The next scan should not flag the same instances of the same issues.

#### CLI
```sh
sonar-export "https://sonarcloud.io/project/issues?open=ISSUE_KEY&id=PROJECT_KEY"
```
