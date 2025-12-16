# Job Scraper Web Interface

A beautiful web dashboard to scrape job listings from LinkedIn and RubyOnRemote.

## Features

- 🎨 Modern, responsive web interface
- 🔄 Real-time job status updates
- 📊 Job history tracking
- 📥 Direct CSV download
- 🎯 Support for both LinkedIn and RubyOnRemote
- ⚙️ Configurable scraping parameters

## Installation

1. Install the required dependencies:

```bash
pip install -r requirement.txt
```

## Usage

1. Start the web server:

```bash
python app.py
```

2. Open your browser and navigate to:

```url
http://localhost:5000
```

3. Fill in the scraping parameters:
   - **Platform**: Choose between LinkedIn or RubyOnRemote
   - **Job Keywords**: Enter the job title or keywords (e.g., "Ruby on Rails")
   - **Location**: Enter the location (e.g., "Japan", "US", "Europe")
   - **Max Pages**: Number of pages to scrape (1-10)
   - **Headless Mode**: Check to run browser in background (faster but you can't see the progress)

2. Click "Start Scraping" and monitor the progress in real-time

3. Download the results as CSV when the job completes

## How It Works

- **Frontend**: HTML/CSS/JavaScript with a modern, gradient design
- **Backend**: Flask web server that manages scraping jobs
- **Scraping**: Runs your existing `linkedin_v2.py` and `rubyonremote_v1.py` scripts
- **Real-time Updates**: Status polling updates the UI every 2 seconds

## File Structure

```python
.
├── app.py                    # Flask backend server
├── templates/
│   └── index.html           # Main web interface
├── static/
│   ├── style.css            # Styling
│   └── script.js            # Frontend logic
├── linkedin_v2.py           # LinkedIn scraper (existing)
├── rubyonremote_v1.py       # RubyOnRemote scraper (existing)
└── requirements_web.txt     # Web dependencies
```

## Notes

- The web interface creates temporary copies of your scraper scripts with the configured parameters
- Output files are saved in the same directory with the naming pattern:
  - LinkedIn: `linkedin_{keywords}_{location}.csv`
  - RubyOnRemote: `rubyonremote_{keywords}_{location}.csv`
- Job history is kept in memory and will reset when you restart the server

## Troubleshooting

### Timeout Errors

**Problem:** `Connection timeout` or `ReadTimeoutError`

**Solutions:**
- Reduce the number of pages to scrape (try 1-2 pages first)
- Disable headless mode to see what's happening in the browser
- Check your internet connection speed
- The website might be experiencing high load or blocking automated requests
- Try again later when the website is less busy
- The scraper will automatically timeout after 10 minutes

### Login Required (LinkedIn)

**Problem:** LinkedIn asks you to log in

**Solutions:**
- Disable headless mode before starting
- When the browser opens, manually log in to LinkedIn
- Wait for the jobs search page to load
- The scraper will detect when you're logged in and continue

### Browser Driver Issues

**Problem:** `WebDriverException` or browser won't start

**Solutions:**
- Make sure Chrome or Edge browser is installed
- Try running: `pip install --upgrade selenium webdriver-manager`
- Close all Chrome/Edge windows before running
- On Linux, you may need to install: `sudo apt-get install chromium-browser`

### No Results Found

**Problem:** Scraping completes but finds 0 results

**Solutions:**
- Check if your search keywords and location are correct
- Try broader search terms (e.g., "Developer" instead of "Senior Ruby on Rails Developer")
- The location might not have jobs matching your criteria
- Try a different platform (LinkedIn vs RubyOnRemote)

### Slow Performance

**Solutions:**
- Enable headless mode (faster, but you can't see progress)
- Reduce max pages to scrape (1-3 recommended)
- Close other browser windows
- Free up system memory

### Other Issues

**Port already in use**: Change the port in `app.py` (last line) to a different number

**Script not found**: Make sure `linkedin_v2.py` and `rubyonremote_v1.py` are in the same directory as `app.py`
