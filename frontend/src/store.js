import { reactive } from "vue";

export const store = reactive({
  storeName: "魔克摩托改装",
  llmReady: false,
  llmChecked: false,
  agent: {
    running: false,
    startedAt: null,
    interval: 30,
    dry: false,
    eventCount: 0,
    lastEvent: null,
    stats: {
      rounds: 0, handled: 0, human: 0, refund: 0,
      unknown: 0, ack: 0, send: 0, errors: 0,
    },
  },
});
