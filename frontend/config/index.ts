import { defineConfig } from '@tarojs/cli'
export default defineConfig({
  projectName: 'LevelUProject',
  date: '2026-10-12',
  designWidth: 390,
  deviceRatio: { 390: 750 / 390 },
  sourceRoot: 'src',
  outputRoot: process.env.TARO_ENV === 'h5' ? 'dist-h5' : 'dist',
  framework: 'react',
  compiler: { type: 'webpack5', prebundle: { enable: false } },
  cache: { enable: false },
  sass: { data: `$levelup-weapp: ${process.env.TARO_ENV === 'weapp'};` },
  defineConstants: {
    API_BASE: JSON.stringify(process.env.API_BASE || 'http://127.0.0.1:8000'),
    MINI_CODE_URL: JSON.stringify(process.env.MINI_CODE_URL || ''),
  },
  mini: {
    // Taro 4.3 treats numeric limit=0 as its default inline threshold.
    // Asset resources always pass short local paths to native Image components.
    webpackChain(chain) { chain.module.rule('image').set('type', 'asset/resource') },
    postcss: { pxtransform: { enable: true }, url: { enable: true, config: { limit: 0 } } },
  },
  h5: {
    publicPath: '/',
    staticDirectory: 'static',
    router: { mode: 'hash' },
    devServer: { host: '127.0.0.1', port: Number(process.env.LEVELUP_H5_PORT || 10086) },
    postcss: { pxtransform: { enable: false } },
  },
})
