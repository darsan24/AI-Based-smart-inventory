import os
import subprocess

with open('static/forecast_preview.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Loading state
loading_html = html.replace('id="retrainAllOverlay" style="display:none;', 'id="retrainAllOverlay" style="display:flex;')
with open('static/preview_loading.html', 'w', encoding='utf-8') as f:
    f.write(loading_html)

# 2. Result state
result_html = loading_html.replace('id="retrainAllSpinner"', 'id="retrainAllSpinner" style="display:none;"')
result_html = result_html.replace('id="retrainAllResult" style="display:none;"', 'id="retrainAllResult" style="display:block;"')
result_html = result_html.replace('<div id="retrainAllResultIcon" class="mb-3"></div>', '<div id="retrainAllResultIcon" class="mb-3"><i class="fa-solid fa-circle-check text-success" style="font-size:3rem;"></i></div>')
result_html = result_html.replace('<h5 id="retrainAllResultTitle" class="fw-bold text-dark mb-2"></h5>', '<h5 id="retrainAllResultTitle" class="fw-bold text-dark mb-2">All Products Retrained Successfully</h5>')
result_html = result_html.replace('<p id="retrainAllResultBody" class="text-secondary mb-3"></p>', '<p id="retrainAllResultBody" class="text-secondary mb-3"><strong>19 of 19</strong> products retrained and forecasted.</p>')

with open('static/preview_result.html', 'w', encoding='utf-8') as f:
    f.write(result_html)

chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
temp_dir = os.environ.get('TEMP', r'C:\Users\Selva\AppData\Local\Temp')

# Screenshot 1: Loading
cmd_loading = f'"{chrome_path}" --headless=new --user-data-dir="{temp_dir}\\chrometmp_load" --window-size=1440,900 --screenshot="C:\\Users\\Selva\\Documents\\mini project\\static\\screenshot_loading.png" "file:///C:/Users/Selva/Documents/mini project/static/preview_loading.html"'
subprocess.run(f'cmd /c "{cmd_loading}"', shell=True)

# Screenshot 2: Result
cmd_result = f'"{chrome_path}" --headless=new --user-data-dir="{temp_dir}\\chrometmp_res" --window-size=1440,900 --screenshot="C:\\Users\\Selva\\Documents\\mini project\\static\\screenshot_result.png" "file:///C:/Users/Selva/Documents/mini project/static/preview_result.html"'
subprocess.run(f'cmd /c "{cmd_result}"', shell=True)

print("Screenshots captured successfully.")
