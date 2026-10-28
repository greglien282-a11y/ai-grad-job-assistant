import { expect, it } from 'vitest'
import fixtures from '../../../../../research/m25_quality/contract-fixtures.json'
import { parsePacket } from './contract'

it.each(fixtures.valid.map((packet, i) => ({ packet, i })))('shares Python/TS accepted code-point contract fixture $i', ({ packet }) => {
  expect(parsePacket(packet)).toEqual(packet)
})
it.each(fixtures.invalid)('shares Python/TS rejected contract fixture $name', ({ packet }) => {
  expect(() => parsePacket(packet)).toThrow()
})
