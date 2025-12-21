# File Cleanup and Pagination Features

This document describes the new file cleanup and screenshots gallery pagination features added to subScraper.

## File Cleanup System

The application now automatically removes old files it no longer needs to keep disk usage under control.

### What Gets Cleaned Up

1. **Temporary Files** (older than 24 hours by default):
   - `.tmp.*` files (e.g., `config.tmp.12345`)
   - `.backup` files (e.g., `state.backup`)
   - `.restore_temp` directories

2. **Old Scan Result Files** (older than 30 days by default):
   - `nuclei_*.json` files
   - `nikto_*.json` files
   - `httpx_*.json` files
   - `ffuf_*.json` files

3. **Old Backups** (keeps only the most recent N backups as configured)

### Configuration

The cleanup system can be configured through the web UI Settings or in `recon_data/config.json`:

```json
{
  "auto_cleanup_enabled": true,
  "cleanup_scan_results_days": 30,
  "cleanup_temp_files_hours": 24,
  "cleanup_interval": 3600
}
```

**Settings:**
- `auto_cleanup_enabled` (boolean): Enable/disable automatic cleanup (default: true)
- `cleanup_scan_results_days` (integer): Number of days to keep scan result files (default: 30)
- `cleanup_temp_files_hours` (integer): Number of hours to keep temporary files (default: 24)
- `cleanup_interval` (integer): Cleanup interval in seconds (default: 3600 = 1 hour)

### Using the Cleanup System

#### Automatic Cleanup

When `auto_cleanup_enabled` is true, the cleanup worker runs automatically in the background at the configured interval.

#### Manual Cleanup

You can trigger cleanup manually via the API:

```bash
# Check cleanup status
curl http://127.0.0.1:8342/api/cleanup-status

# Manually trigger cleanup
curl -X POST http://127.0.0.1:8342/api/cleanup/run
```

Response example:
```json
{
  "success": true,
  "message": "Cleanup completed: 2 temp files, 3 scan results, 1 backups removed",
  "stats": {
    "temp_files": 2,
    "scan_results": 3,
    "backups": 1
  }
}
```

### Cleanup Logs

Cleanup operations are logged to the console with timestamps:

```
[2025-12-21 15:12:09 UTC] 🗑️  Removed old temp file: test.tmp.12345
[2025-12-21 15:12:09 UTC] 🗑️  Removed old scan result: nuclei_testdomain.json
[2025-12-21 15:12:09 UTC] ✓ Cleaned up 2 temporary file(s)
```

## Screenshots Gallery Pagination

The screenshots gallery page now includes pagination to handle large numbers of screenshots efficiently.

### Features

- **Configurable Page Size**: Default is 20 screenshots per page
- **Top and Bottom Controls**: Pagination controls appear at both the top and bottom of the gallery
- **Navigation Buttons**:
  - `«` First page
  - `‹` Previous page
  - `›` Next page
  - `»` Last page
- **Page Information**: Shows "Page X of Y (showing A-B of Total)"
- **Smooth Scrolling**: Automatically scrolls to top when changing pages
- **Lazy Loading**: Images still load lazily as they come into view

### Configuration

Set the number of screenshots per page in `recon_data/config.json`:

```json
{
  "screenshots_per_page": 20
}
```

### Usage

1. Navigate to the screenshots gallery for any domain:
   - From the dashboard, click on a domain
   - Click the "Screenshots Gallery" link
   - Or visit `/gallery/<domain>` directly

2. Use the pagination controls to navigate through pages:
   - Click `«` to jump to the first page
   - Click `‹` to go to the previous page
   - Click `›` to go to the next page
   - Click `»` to jump to the last page

3. The page information shows your current position:
   - Example: "Page 2 of 5 (showing 21-40 of 87)"

### Example

If you have 87 screenshots and `screenshots_per_page` is set to 20:
- Page 1: Screenshots 1-20
- Page 2: Screenshots 21-40
- Page 3: Screenshots 41-60
- Page 4: Screenshots 61-80
- Page 5: Screenshots 81-87

## Benefits

### File Cleanup
- **Reduced Disk Usage**: Automatically removes old files that are no longer needed
- **Better Performance**: Fewer files to scan when loading data
- **Cleaner Workspace**: Keeps the `recon_data` directory organized
- **Configurable Retention**: Adjust retention periods based on your needs

### Gallery Pagination
- **Better Performance**: Only loads a subset of screenshots at a time
- **Improved User Experience**: Easier to browse large collections
- **Responsive Design**: Works well on all screen sizes
- **Maintains Features**: Lazy loading and modal view still work perfectly

## Migration

These features are backwards compatible and require no migration:
- Cleanup is enabled by default with conservative settings (30 days)
- Pagination works automatically for all existing galleries
- Old files are preserved until they exceed the retention period
- Configuration settings have sensible defaults

## Troubleshooting

### Cleanup Not Running

1. Check if cleanup is enabled:
   ```bash
   curl http://127.0.0.1:8342/api/cleanup-status
   ```

2. Look for `"enabled": true` and `"worker_active": true` in the response

3. Check the logs for cleanup messages

### Pagination Not Showing

1. Pagination only appears when there are more screenshots than the page size
2. Check `screenshots_per_page` in settings (default: 20)
3. If you have fewer than 20 screenshots, pagination won't display

### Files Not Being Cleaned

1. Check file ages - only files older than the configured retention period are removed
2. Verify the cleanup worker is running: `"worker_active": true`
3. Manually trigger cleanup to test: `POST /api/cleanup/run`

## API Reference

### GET /api/cleanup-status

Get the current status of the cleanup system.

**Response:**
```json
{
  "enabled": true,
  "interval_seconds": 3600,
  "scan_results_retention_days": 30,
  "temp_files_retention_hours": 24,
  "last_cleanup_timestamp": 1703174529.123,
  "next_cleanup_timestamp": 1703178129.123,
  "next_cleanup": "2025-12-21T16:12:09Z",
  "worker_active": true
}
```

### POST /api/cleanup/run

Manually trigger a cleanup operation.

**Response:**
```json
{
  "success": true,
  "message": "Cleanup completed: 2 temp files, 3 scan results, 1 backups removed",
  "stats": {
    "temp_files": 2,
    "scan_results": 3,
    "backups": 1
  }
}
```
