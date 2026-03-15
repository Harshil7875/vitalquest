const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

// Enable React Native Web
config.resolver.sourceExts.push('mjs');

module.exports = config;
