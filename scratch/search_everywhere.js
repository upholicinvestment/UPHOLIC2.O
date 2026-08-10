import fs from 'fs';
import path from 'path';

const searchDirs = [
  'c:\\Users\\rohit\\OneDrive\\Desktop\\UPL',
  'c:\\Users\\rohit\\OneDrive\\Desktop\\UPHOLIC',
];

function searchDir(dir, query) {
  let files;
  try {
    files = fs.readdirSync(dir);
  } catch (err) {
    return;
  }

  for (const file of files) {
    const fullPath = path.join(dir, file);
    let stats;
    try {
      stats = fs.statSync(fullPath);
    } catch (err) {
      continue;
    }

    if (stats.isDirectory()) {
      if (file !== 'node_modules' && file !== '.git' && file !== 'dist') {
        searchDir(fullPath, query);
      }
    } else if (stats.isFile()) {
      const ext = path.extname(file).toLowerCase();
      if (['.js', '.ts', '.json', '.py', '.php', '.env'].includes(ext)) {
        try {
          const content = fs.readFileSync(fullPath, 'utf8');
          if (content.toLowerCase().includes(query.toLowerCase())) {
            console.log(`Found match in: ${fullPath}`);
            const lines = content.split('\n');
            lines.forEach((line, idx) => {
              if (line.toLowerCase().includes(query.toLowerCase())) {
                console.log(`  Line ${idx + 1}: ${line.trim()}`);
              }
            });
          }
        } catch (err) {
          // ignore read errors
        }
      }
    }
  }
}

console.log("Searching for 'optstk_live'...");
for (const d of searchDirs) {
  searchDir(d, 'optstk_live');
}

console.log("Searching for 'optstklive'...");
for (const d of searchDirs) {
  searchDir(d, 'optstklive');
}
