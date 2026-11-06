"""Exercise the static site in Chromium. Start a local HTTP server first.

Use --generate to run the full, resource-intensive master approval/export test.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000/')
    parser.add_argument('--generate',action='store_true')
    parser.add_argument('--no-sandbox',action='store_true',help='For restricted test containers only')
    parser.add_argument('--screenshots',type=Path)
    args=parser.parse_args()
    with sync_playwright() as p:
        options={'headless':True,'args':['--no-sandbox'] if args.no_sandbox else []}
        executable=shutil.which('chromium')
        if executable:options['executable_path']=executable
        if os.environ.get('HTTPS_PROXY'):
            options['proxy']={'server':os.environ['HTTPS_PROXY'],'bypass':'localhost,127.0.0.1'}
        browser=p.chromium.launch(**options)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url)
        if args.screenshots:
            args.screenshots.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(args.screenshots/'desktop.png'),full_page=True)
        page.locator('#subject').fill('an owl')
        page.locator('#step-1 button[type=submit]').click()
        assert 'currently available' in page.locator('#notice').inner_text()
        page.locator('[data-subject]').click()
        page.locator('#step-1 button[type=submit]').click()
        page.locator('#layers').fill('2.5')
        page.locator('#step-2 button[type=submit]').click()
        assert 'whole number' in page.locator('#notice').inner_text()
        page.locator('#layers').fill('5')
        page.locator('#step-2 button[type=submit]').click()
        page.locator('input[name=reference][value=upload]').check()
        page.locator('#reference-file').set_input_files({'name':'bad.txt','mimeType':'text/plain','buffer':b'bad'})
        assert 'PNG or JPEG' in page.locator('#notice').inner_text()
        page.locator('input[name=reference][value=sample]').check()
        page.locator('#step-3 button[type=submit]').click()
        if args.generate:
            page.wait_for_selector('#review-panel:not([hidden])',timeout=600_000)
            page.locator('#approve-button').click()
            page.wait_for_selector('#download-panel:not([hidden])',timeout=900_000)
            page.locator('[data-tab=checks]').click()
            assert 'reviewed master stayed unchanged' in page.locator('#checks-view').inner_text()
            with tempfile.TemporaryDirectory() as directory:
                with page.expect_download() as event:page.locator('#download-zip').click()
                path=Path(directory)/'set.zip';event.value.save_as(path)
                with zipfile.ZipFile(path) as archive:
                    assert archive.testzip() is None
                    report=json.loads(archive.read('validation_report.json'))
                    assert report['passed'] and report['reviewed_master_unchanged']
        else:
            page.locator('#cancel-button').click()
            assert page.locator('#step-3').is_visible()
            page.locator('#example-button').click()
            page.wait_for_selector('#download-panel:not([hidden])')
        page.locator('[data-tab=layers]').click()
        assert page.locator('.layer-tile').count()==5
        page.locator('.layer-tile button').first.click()
        assert page.locator('#image-dialog').is_visible()
        page.keyboard.press('Escape')
        page.locator('#another-button').click()
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        if args.screenshots:page.screenshot(path=str(args.screenshots/'mobile.png'),full_page=True)
        page.locator('#how-button').click();page.locator('#how-example-button').click()
        page.wait_for_selector('#download-panel:not([hidden])')
        assert not errors,errors
        browser.close()
        print('Browser workflow passed'+(' including a full 600-DPI export.' if args.generate else '.'))


if __name__=='__main__':main()
