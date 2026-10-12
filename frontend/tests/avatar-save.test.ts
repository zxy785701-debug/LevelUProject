import { beforeEach, expect, test, vi } from 'vitest'
const native = vi.hoisted(() => ({ saveImageToPhotosAlbum: vi.fn(), showModal: vi.fn(), openSetting: vi.fn() }))
vi.mock('@tarojs/taro', () => ({ default: native }))
import { saveAvatarImage } from '../src/platform'
beforeEach(() => { vi.clearAllMocks() })

test('微信保存使用已鉴权下载的本地图片路径', async () => {
  native.saveImageToPhotosAlbum.mockResolvedValue({})
  await saveAvatarImage('wxfile://avatar.jpg')
  expect(native.saveImageToPhotosAlbum).toHaveBeenCalledWith({ filePath: 'wxfile://avatar.jpg' })
  expect(native.showModal).not.toHaveBeenCalled()
})

test('拒绝相册权限后可打开设置，保留头像并允许重试', async () => {
  native.saveImageToPhotosAlbum.mockRejectedValue({ errMsg: 'saveImageToPhotosAlbum:fail auth deny' })
  native.showModal.mockResolvedValue({ confirm: true })
  await expect(saveAvatarImage('wxfile://avatar.jpg')).rejects.toThrow('头像仍然保留')
  expect(native.openSetting).toHaveBeenCalledOnce()
})

test('用户选择稍后再试时不打开设置', async () => {
  native.saveImageToPhotosAlbum.mockRejectedValue({ errMsg: 'saveImageToPhotosAlbum:fail auth deny' })
  native.showModal.mockResolvedValue({ confirm: false })
  await expect(saveAvatarImage('wxfile://avatar.jpg')).rejects.toThrow('头像仍然保留')
  expect(native.openSetting).not.toHaveBeenCalled()
})

test('取消保存不会弹出相册权限设置提示', async () => {
  native.saveImageToPhotosAlbum.mockRejectedValue({ errMsg: 'saveImageToPhotosAlbum:fail cancel' })
  await expect(saveAvatarImage('wxfile://avatar.jpg')).rejects.toThrow('已取消保存')
  expect(native.showModal).not.toHaveBeenCalled()
})
