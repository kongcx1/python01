const fs = require('fs')
const path = require('path')
const SparkMD5 = require('../telegram_download_admin_vue/node_modules/spark-md5')

const target = process.argv[2]

if (!target) {
  console.error('usage: node spark_md5_file.js <file>')
  process.exit(2)
}

const absolute = path.resolve(target)
const spark = new SparkMD5.ArrayBuffer()
const stream = fs.createReadStream(absolute, { highWaterMark: 2 * 1024 * 1024 })

stream.on('data', chunk => {
  const arrayBuffer = chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + chunk.byteLength)
  spark.append(arrayBuffer)
})

stream.on('error', error => {
  console.error(error && error.message ? error.message : String(error))
  process.exit(1)
})

stream.on('end', () => {
  console.log(spark.end())
})
