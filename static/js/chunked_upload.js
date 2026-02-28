(function (global) {
  'use strict';

  async function parseJsonSafe(response) {
    try {
      return await response.json();
    } catch (_e) {
      return {};
    }
  }

  function formatErrorMessage(prefix, response, data) {
    if (data && typeof data.message === 'string' && data.message.trim()) {
      return data.message;
    }
    return `${prefix} (${response.status})`;
  }

  async function uploadPdfInChunks(file, options = {}) {
    const initEndpoint = options.initEndpoint || '/api/upload_pdf_chunk/init';
    const partEndpoint = options.partEndpoint || '/api/upload_pdf_chunk/part';
    const completeEndpoint = options.completeEndpoint || '/api/upload_pdf_chunk/complete';
    const onProgress = typeof options.onProgress === 'function' ? options.onProgress : null;

    const initRes = await fetch(initEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: file.name,
        size: file.size,
        last_modified_ms: String(file.lastModified || ''),
      }),
    });
    const initData = await parseJsonSafe(initRes);
    if (!initRes.ok || initData.status !== 'ok') {
      throw new Error(formatErrorMessage('分割アップロードの初期化に失敗しました', initRes, initData));
    }

    const uploadId = String(initData.upload_id || '');
    const chunkSize = Number(initData.chunk_size || 0);
    const totalChunks = Number(initData.total_chunks || 0);

    if (!uploadId || chunkSize <= 0 || totalChunks <= 0) {
      throw new Error('分割アップロードの初期化レスポンスが不正です');
    }

    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex += 1) {
      const start = chunkIndex * chunkSize;
      const end = Math.min(file.size, start + chunkSize);
      const chunkBlob = file.slice(start, end);

      const form = new FormData();
      form.append('upload_id', uploadId);
      form.append('chunk_index', String(chunkIndex));
      form.append('chunk', chunkBlob, `${file.name}.part${chunkIndex}`);

      const partRes = await fetch(partEndpoint, {
        method: 'POST',
        body: form,
      });
      const partData = await parseJsonSafe(partRes);
      if (!partRes.ok || partData.status !== 'ok') {
        throw new Error(formatErrorMessage('分割アップロード中に失敗しました', partRes, partData));
      }

      if (onProgress) {
        onProgress({
          uploadedBytes: end,
          totalBytes: file.size,
          chunkIndex,
          totalChunks,
        });
      }
    }

    const completeRes = await fetch(completeEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ upload_id: uploadId }),
    });
    const completeData = await parseJsonSafe(completeRes);
    if (!completeRes.ok || completeData.status !== 'ok') {
      throw new Error(formatErrorMessage('分割アップロードの完了処理に失敗しました', completeRes, completeData));
    }

    return completeData;
  }

  global.ChunkedPdfUpload = {
    uploadPdfInChunks,
  };
})(window);
