import axios from 'axios'
import { computed, ref } from 'vue'

const pendingRequestCount = ref(0)
export const isRequestLoading = computed(() => pendingRequestCount.value > 0)

const client = axios.create({ baseURL: '/api' })

function settleRequest(config) {
  if (!config || !config.__stoichRequestTracked) return
  config.__stoichRequestTracked = false
  pendingRequestCount.value = Math.max(0, pendingRequestCount.value - 1)
}

client.interceptors.request.use((config) => {
  if (!config.__stoichRequestTracked) {
    config.__stoichRequestTracked = true
    pendingRequestCount.value += 1
  }
  return config
})

client.interceptors.response.use(
  (response) => {
    settleRequest(response.config)
    return response
  },
  (error) => {
    settleRequest(error?.config)
    return Promise.reject(error)
  },
)

export default client
