import SparkMD5 from 'spark-md5'

export function md5ArrayBuffer(buffer) {
  return SparkMD5.ArrayBuffer.hash(buffer)
}

export function md5File(file, chunkSize = 2 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const spark = new SparkMD5.ArrayBuffer()
    const reader = new FileReader()
    const chunks = Math.ceil(file.size / chunkSize)
    let index = 0

    reader.onload = event => {
      spark.append(event.target.result)
      index += 1
      if (index < chunks) {
        loadNext()
      } else {
        resolve(spark.end())
      }
    }

    reader.onerror = () => reject(reader.error)

    function loadNext() {
      const start = index * chunkSize
      const end = Math.min(start + chunkSize, file.size)
      reader.readAsArrayBuffer(file.slice(start, end))
    }

    loadNext()
  })
}
