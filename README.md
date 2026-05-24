# sonar-issue-exporter

### AI Disclosure and Disclaimer
I am neither a developer nor affiliated with Sonar. The Python scripts in this repo are vibe-coded with [DeepSeek](https://chat.deepseek.com/) and [Z.ai](https://chat.z.ai/). The scripts are intended for [Web API](https://docs.sonarsource.com/sonarqube-cloud/appendices/web-api) usage with a free tier SonarQube Cloud account linked to a public, open-source repo. I have only tested them with GitHub on Windows. They might also work for repos on GitLab, Bitbucket, and Azure Cloud on any OS where Python is supported. See chat history in /ai/chat.

### About
sonar-issue-exporter is a tool for downloading SonarQube Cloud issues to text files that an AI can read. It was created to help fix maintainability issues in my other vibe-coded app (LineByLine).

## Setup (GitHub)
1. Add a SonarCloud analysis GitHub workflow to your GitHub repo. Follow the instructions in the sonarcloud.yml template.
2. Go to your repo Settings/Rules/Rulesets → Require code scanning results and add SonarCloud. It should now scan before any commit.
3. Download export_sonar_issue.py, watch_clipboard.py, and sample.env (or git pull the repo).
4. Go to your SonarQube Cloud account → Security (shield icon) in left ribbon → Generate Tokens → Enter some name you'll remember → Copy the token
5. Rename sample.env to .env and paste the token between the quotes in `BEARER_TOKEN=""`
6. Install Python dependencies: `pip install html2text pyperclip`

## Usage
1. Open a Sonar page with issues.
2. Make the Python scripts executable if on Linux. Double-click watch_clipboard.py to open a terminal window showing links it found.
3. `Alt+Tab` back to the Sonar page. Copy each issue's link (on Firefox, right click the blue titles and press `L`, scrolling down as needed) and wait for subfolders to appear in the script folder. Currently, each issue should be represented with a long named subfolder containing:
	1. where.json - aka "Where is the issue?"
	2. why.md - aka "Why is this an issue?" if available
	3. how.md - aka "How can I fix it?" if available
4. Close the terminal window when finished.
5. Upload the folders (as a zip) and their associated app file(s) to a free AI web chat like chat.z.ai or claude.ai. They may generate a table of their findings and fixes they made. Ask them to include the line affected (i.e. L303) so you can `Ctrl+F` the Sonar project Issues page. Update each unchanged (i.e. "Won't Fix", "defer until refactor") issue's status from Open to "Accept" or "False Positive". If the AI fixed an issue, leave the status Open instead of changing to "Fixed". The next scan should not flag the same instances of the same issues. New future instances of the same issues (even False Positives) may still be flagged.

## Planned features
- Custom download path .env variable
- Download progress indicators in terminal window
- Deduplication of same issue category folders and identical .md files