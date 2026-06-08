#!/usr/bin/env bash
# Extract the <script> body from index.html and node --check it.
set -e
node -e '
const fs=require("fs");
const html=fs.readFileSync("index.html","utf8");
const m=html.match(/<script>([\s\S]*?)<\/script>/);
if(!m){console.error("no <script> found");process.exit(2);}
fs.writeFileSync("/tmp/maze-script.js",m[1]);
'
node --check /tmp/maze-script.js && echo "node --check OK"
