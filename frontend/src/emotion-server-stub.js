// Stub de @emotion/server/create-instance para o browser.
// @leafygreen-ui/emotion chama createEmotionServer(cache) no topo do módulo, o que
// puxa html-tokenize/readable-stream (APIs Node) e quebra no navegador. Essas funções
// só servem para SSR (extração de CSS crítico), que um SPA cliente nunca usa.
export default function createEmotionServer() {
  return {
    extractCritical: (html) => ({ html, ids: [], css: '' }),
    renderStylesToString: (html) => html,
    renderStylesToNodeStream: () => {
      throw new Error('renderStylesToNodeStream não é suportado no browser')
    },
  }
}
