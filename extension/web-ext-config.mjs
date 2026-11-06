// web-ext build / sign / run: personal files never go into the package that is uploaded to Mozilla for signing;
// a signed build gets the profile and the CV through the options page (storage.local) instead.
export default {
  ignoreFiles: ['profile.json', 'cv.pdf', 'profile.example.json', 'test', 'node_modules', 'package.json',
    'package-lock.json', 'web-ext-config.mjs', 'README.md', 'sign.sh'],
};
