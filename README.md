# sonar-issue-exporter

### AI Disclosure and Disclaimer
I am neither a developer nor affiliated with Sonar. The Python scripts in this repo are vibe-coded with [DeepSeek](https://chat.deepseek.com/) and [Z.ai](https://chat.z.ai/). Prompt history for this project is in /ai/chat. I have only tested the scripts with GitHub on Windows. They might also work for repos on GitLab, Bitbucket, and Azure Cloud on any OS where Python is supported.

sonar-issues-exporter is not an official Sonar product. It is a client tool that fetches data from the SonarQube Cloud [Web API](https://docs.sonarsource.com/sonarqube-cloud/appendices/web-api). Users must have their own authorized SonarCloud account and API token. Rule descriptions and educational content are the intellectual property of SonarSource SA. This tool does not bundle or redistribute SonarSource content.

### About
sonar-issue-exporter is a tool for downloading SonarQube Cloud issues to text files that an AI can read. It was created to help fix maintainability issues in my other vibe-coded app (LineByLine).

## Setup

#### SonarCloud GitHub Action
1. Add a SonarCloud analysis GitHub workflow to your GitHub repo. Follow the instructions in the sonarcloud.yml template.
2. Go to your repo Settings/Rules/Rulesets → Require code scanning results and add SonarCloud. It should now scan before any commit.
3. Go to your SonarQube Cloud account → Security (shield icon) in left ribbon → Generate Tokens → Enter some name you'll remember → Copy the token and save it to a password manager like KeepassXC

#### Python
1. Install [Python 3.8+](https://www.python.org/downloads/).
2. Install sonar-issue-exporter:
   ```
   pip install git+https://github.com/amokprime/sonar-issue-exporter.git
   ```
   Or clone the repo and run `pip install .`

   To get better Markdown output, install with the optional extra:
   ```
   pip install "sonar-issue-exporter[markdown] @ git+https://github.com/amokprime/sonar-issue-exporter.git"
   ```
3. Create a `.env` file **in the directory where you'll run the commands**, paste your token between the quotes, and save:
   ```
   BEARER_TOKEN="your-token-here"
   ```

## Usage
1. Open a Sonar page with issues.
2. Run `sonar-watch` from a terminal. (If you cloned the repo instead of using pip install, double-click `watch_clipboard.py` or run `python watch_clipboard.py`.)
3. `Alt+Tab` back to the Sonar page. Copy each issue's link (on Firefox, right click the blue titles and press `L`, scrolling down as needed) and wait for subfolders to appear in the terminal's working directory. Each issue is represented by a subfolder containing:
	1. where.json - "Where is the issue?"
	2. why.md - "Why is this an issue?" if available
	3. how.md - "How can I fix it?" if available
   why.md and how.md are hidden by .gitignore to avoid redistributing SonarSource content.
7. Close the terminal window when finished.
8. Upload the folders (as a zip) and their associated app file(s) to a free AI web chat like chat.z.ai or claude.ai. They may generate a table of their findings and fixes they made. Ask them to include the line affected (i.e. L303) so you can `Ctrl+F` the Sonar project Issues page. Update each unchanged (i.e. "Won't Fix", "defer until refactor") issue's status from Open to "Accept" or "False Positive". If the AI fixed an issue, leave the status Open instead of changing to "Fixed". The next scan should not flag the same instances of the same issues. New future instances of the same issues (even False Positives) may still be flagged.

### Alternative: export a single issue directly
```
sonar-export "https://sonarcloud.io/project/issues?open=ISSUE_KEY&id=PROJECT_KEY"
```

## Planned features
- Custom download path .env variable
- Download progress indicators in terminal window
- Deduplication of same issue category folders and identical .md files
