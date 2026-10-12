import { defineConfig } from '@tarojs/cli'
export default defineConfig({
  projectName: 'LevelUpComic',
  date: '2026-10-12',
  designWidth: 375,
  deviceRatio: { 375: 2 },
  sourceRoot: 'src',
  outputRoot: process.env.TARO_ENV === 'h5' ? 'dist-h5' : 'dist',
  framework: 'react',
  compiler: { type: 'webpack5', prebundle: { enable: false } },
  cache: { enable: false },
  sass: { data: `$levelup-weapp: ${process.env.TARO_ENV === 'weapp'};` },
  defineConstants: {
    API_BASE: JSON.stringify(process.env.API_BASE || (process.env.TARO_ENV === 'h5' ? '' : 'http://127.0.0.1:8000')),
    MINI_CODE_URL: JSON.stringify(process.env.MINI_CODE_URL || ''),
  },
  mini: { postcss: { pxtransform: { enable: true }, url: { enable: true, config: { limit: 0 } } } },
  h5: {
    publicPath: '/',
    staticDirectory: 'static',
    router: { mode: 'hash' },
    devServer: { host: '127.0.0.1', port: Number(process.env.LEVELUP_H5_PORT || 10087), proxy: { '/api': { target: process.env.COMIC_BACKEND || 'http://127.0.0.1:8000', changeOrigin: true } } },
    postcss: { pxtransform: { enable: false } },
  },
})

