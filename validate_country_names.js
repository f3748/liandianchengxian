const fs = require('fs');
const vm = require('vm');

function extractObjectLiteral(source, marker) {
  const start = source.indexOf(marker);
  if (start < 0) throw new Error(`Cannot find ${marker}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    const char = source[index];
    if (char === '{') depth += 1;
    if (char === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(brace, index + 1);
    }
  }
  throw new Error(`Cannot parse ${marker}`);
}

const indexHtml = fs.readFileSync('index.html', 'utf8');
const historicalCountryNames = vm.runInNewContext(`(${extractObjectLiteral(indexHtml, 'const historicalCountryNames = {')})`);
const historicalCountryNameAliases = vm.runInNewContext(`(${extractObjectLiteral(indexHtml, 'const historicalCountryNameAliases = {')})`);

const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('map-data.js', 'utf8'), sandbox);

const datasets = [sandbox.window.HISTORICAL_MAP_DATA, sandbox.window.WW2_EUROPE_MAP_DATA];
const rawNames = new Set();
for (const dataset of datasets) {
  for (const featureCollection of Object.values(dataset || {})) {
    for (const feature of featureCollection.features || []) {
      if (feature.properties?.NAME) rawNames.add(feature.properties.NAME);
    }
  }
}
for (const feature of sandbox.window.WW1_EUROPE_MAP_DATA?.features || []) {
  if (feature.properties?.NAME) rawNames.add(feature.properties.NAME);
}

const knownTypoNames = [
  'Kongldom of Hawaii',
  'Sultinate of Zanzibar',
  'M?ori',
  'Kingfom of Italy',
  'Anglo-Egyption Sudan',
  'Cyraneica (UK Lybia)',
  'Tripolitana (UK Lybia)',
  'Fezzan (Frech Lybia)'
];

const requiredTranslatedNames = [
  'German Empire', 'Germany', 'Austrian Empire', 'Austro-Hungarian Empire', 'Austria Hungary',
  'France', 'United Kingdom', 'United Kingdom of Great Britain and Ireland', 'United States',
  'United States of America', 'Russian Empire', 'USSR', 'Soviet Union', 'Ottoman Empire',
  'Ottoman Sultanate', 'Turkey', 'Kingdom of Italy', 'Italy', 'Spain', 'Portugal', 'Netherlands',
  'Belgium', 'Switzerland', 'Luxembourg', 'Canada', 'Australia', 'New Zealand', 'Union of South Africa',
  'Mexico', 'Brazil', 'Argentina', 'Manchu Empire', 'Republic of China', "People's Republic of China",
  'Republic of China (Taiwan)', 'Japan', 'Empire of Japan', 'Japan (USA)', 'British India', 'British Raj',
  'Persia', 'Iran', 'Afghanistan', 'Egypt', 'India', 'Pakistan', 'Poland', 'Czechoslovakia',
  'Yugoslavia', 'Kingdom of Serbs, Croats and Slovenes'
];

const missingAliases = knownTypoNames.filter(name => rawNames.has(name) && !historicalCountryNameAliases[name]);
const missingTranslations = knownTypoNames
  .filter(name => rawNames.has(name))
  .map(name => historicalCountryNameAliases[name])
  .filter(canonicalName => !historicalCountryNames[canonicalName]);
const missingRequiredTranslations = requiredTranslatedNames
  .filter(name => rawNames.has(name) || historicalCountryNames[name])
  .filter(name => !historicalCountryNames[name]);

if (missingAliases.length || missingTranslations.length || missingRequiredTranslations.length) {
  console.error('Country-name audit failed.');
  if (missingAliases.length) console.error('Missing aliases:', missingAliases.join(', '));
  if (missingTranslations.length) console.error('Missing translations:', missingTranslations.join(', '));
  if (missingRequiredTranslations.length) console.error('Missing required translations:', missingRequiredTranslations.join(', '));
  process.exit(1);
}

console.log(`Country-name audit passed: ${knownTypoNames.filter(name => rawNames.has(name)).length} known source typo aliases and ${requiredTranslatedNames.length} required display names covered.`);
