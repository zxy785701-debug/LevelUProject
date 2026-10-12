import Taro from '@tarojs/taro'
import { Data, Session, stats, typeName } from './domain'
import u from './assets/u-book.png'
import pencil from './assets/pencil.png'
import paper from './assets/paper.png'
const h5 = process.env.TARO_ENV === 'h5'
export async function surface(id: string, width: number, height: number) {
  if (h5) {
    const canvas = document.createElement('canvas')
    canvas.width = width * 2
    canvas.height = height * 2
    const ctx = canvas.getContext('2d')!
    ctx.scale(2, 2)
    return { canvas, ctx }
  }
  const node: any = await new Promise((resolve, reject) =>
    Taro.createSelectorQuery()
      .select(`#${id}`)
      .fields({ node: true, size: true }, (r) =>
        r?.node ? resolve(r.node) : reject(new Error('画布尚未准备好，请重试')),
      )
      .exec(),
  )
  node.width = width * 2
  node.height = height * 2
  const ctx = node.getContext('2d')
  ctx.scale(2, 2)
  return { canvas: node, ctx }
}
async function loadImage(canvas: any, src: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const image = h5 ? new globalThis.Image() : canvas.createImage()
    if (h5) image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('海报图片加载失败，请检查图片地址后重试'))
    image.src = src
  })
}
function lines(
  ctx: any,
  text: string,
  x: number,
  y: number,
  width: number,
  lineHeight: number,
  max: number,
) {
  let line = '',
    rows: string[] = []
  for (const c of text) {
    if (ctx.measureText(line + c).width > width && line) {
      rows.push(line)
      line = c
    } else line += c
  }
  if (line) rows.push(line)
  rows.slice(0, max).forEach((row, i) => {
    if (i === max - 1 && rows.length > max) {
      while (ctx.measureText(row + '…').width > width) row = row.slice(0, -1)
      row += '…'
    }
    ctx.fillText(row, x, y + i * lineHeight)
  })
}
export async function makePoster(s: Session) {
  const { canvas, ctx } = await surface('poster-canvas', 350, 470),
    v = stats(s)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, 350, 470)
  ctx.fillStyle = '#ffd84d'
  ctx.fillRect(0, 0, 350, 9)
  ctx.strokeStyle = '#202a3d'
  ctx.lineWidth = 2
  ctx.strokeRect(1, 1, 348, 468)
  ctx.fillStyle = '#ffd84d'
  ctx.fillRect(22, 28, 27, 28)
  ctx.strokeRect(22, 28, 27, 28)
  ctx.fillStyle = '#202a3d'
  ctx.font = '900 21px sans-serif'
  ctx.fillText('U', 28, 49)
  ctx.font = '900 15px sans-serif'
  ctx.fillText('LevelUProject', 60, 49)
  ctx.font = '900 25px sans-serif'
  ctx.fillText('今天，我搞懂了', 22, 96)
  lines(ctx, s.quiz.title, 22, 131, 306, 34, 2)
  ctx.fillStyle = '#4c5b73'
  ctx.font = '400 15px sans-serif'
  lines(
    ctx,
    '“' + (s.report?.share_quote || '每个问题，都是理解的起点。') + '”',
    22,
    209,
    306,
    27,
    2,
  )
  const pictures = await Promise.all([pencil, u, paper].map((src) => loadImage(canvas, src)))
  const positions = [
    [26, 270, 89, 106],
    [115, 255, 109, 120],
    [235, 278, 86, 92],
  ]
  pictures.forEach((im, i) => {
    const [x, y, w, h] = positions[i]
    const ratio = Math.min(w / im.width, h / im.height)
    ctx.drawImage(im, x + (w - im.width * ratio) / 2, y, im.width * ratio, im.height * ratio)
  })
  ctx.fillStyle = '#202a3d'
  ctx.font = '700 12px sans-serif'
  ctx.fillText(`${v.total} 个问题，带走 ${v.knowledge_points.length} 个知识点`, 22, 414)
  ctx.fillStyle = '#69758a'
  ctx.font = '11px sans-serif'
  ctx.fillText('和我一起，给好奇心升个级。', 22, 439)
  if (MINI_CODE_URL) {
    const im = await loadImage(canvas, MINI_CODE_URL)
    ctx.drawImage(im, 268, 394, 60, 60)
  } else {
    ctx.strokeStyle = '#cad5e7'
    ctx.strokeRect(268, 394, 60, 60)
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('小程序码', 298, 420)
    ctx.fillText('待配置', 298, 438)
    ctx.textAlign = 'left'
  }
  if (h5) return canvas.toDataURL('image/png')
  return (
    await Taro.canvasToTempFilePath({
      canvas,
      x: 0,
      y: 0,
      width: 700,
      height: 940,
      destWidth: 700,
      destHeight: 940,
      fileType: 'png',
    } as any)
  ).tempFilePath
}
export async function savePoster(path: string) {
  if (h5) {
    const a = document.createElement('a')
    a.href = path
    a.download = 'LevelUp-学习收获.png'
    a.click()
    return
  }
  try {
    await Taro.saveImageToPhotosAlbum({ filePath: path })
  } catch {
    const answer = await Taro.showModal({
      title: '需要允许保存图片',
      content: '海报已生成。可在设置中允许访问相册，然后再次点击保存。',
      confirmText: '打开设置',
      cancelText: '稍后再试',
    })
    if (answer.confirm) await Taro.openSetting()
    throw new Error('海报已保留，可再次点击保存')
  }
}
function csvCell(value: unknown) {
  return '"' + String(value ?? '').replace(/"/g, '""') + '"'
}
export function exportCsv(data: Data) {
  const rows = [
    ['主题', '时间', '学习模式', '题型', '题目', '你的答案', '正确答案', '用时毫秒', '讲解'],
  ]
  data.sessions.forEach((s) =>
    s.answers.forEach((a) => {
      const q = s.quiz.questions.find((x) => x.id === a.question_id)!
      rows.push([
        s.quiz.title,
        s.started_at,
        { new: '新学', replay: '重闯', review: '复习' }[s.mode],
        typeName(q.type),
        q.stem,
        a.selected.join('、'),
        q.answers.join('、'),
        String(a.elapsed_ms),
        q.explanation,
      ])
    }),
  )
  return '\uFEFF' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n')
}
export async function saveExport(data: Data) {
  const csv = exportCsv(data),
    fileName = 'LevelUp-学习记录.csv'
  if (h5) {
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = fileName
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    return
  }
  const filePath = `${Taro.env.USER_DATA_PATH}/${fileName}`
  await new Promise((resolve, reject) =>
    Taro.getFileSystemManager().writeFile({
      filePath,
      data: csv,
      encoding: 'utf8',
      success: resolve,
      fail: reject,
    }),
  )
  if (typeof Taro.shareFileMessage === 'function')
    await Taro.shareFileMessage({ filePath, fileName })
  else
    await Taro.showModal({
      title: '导出文件已生成',
      content: '当前微信版本不支持文件分享，请升级微信后重试。',
      showCancel: false,
    })
}
