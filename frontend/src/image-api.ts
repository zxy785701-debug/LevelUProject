import { api, RequestScope } from './api'
import type { ImageCapabilities } from './image-domain'
export const getImageCapabilities = (scope?: RequestScope) => api<ImageCapabilities>(
  '/api/v1/quiz/images/capabilities', 'GET', undefined, undefined, { scope, timeout: 15000 },
)
