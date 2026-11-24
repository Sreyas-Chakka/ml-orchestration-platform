import { describe, expect, it } from 'vitest'
import { fmtBytes, fmtDuration, fmtNum, parseList } from './format'

describe('format helpers', () => {
  it('parses sweep lists into typed values', () => {
    expect(parseList('0.01, 0.1,1')).toEqual([0.01, 0.1, 1])
    expect(parseList('true,false,relu')).toEqual([true, false, 'relu'])
    expect(parseList(' , ')).toEqual([])
  })
  it('formats durations', () => {
    expect(fmtDuration(null)).toBe('—')
    expect(fmtDuration(5.25)).toBe('5.3s')
    expect(fmtDuration(125)).toBe('2m 5s')
    expect(fmtDuration(7260)).toBe('2h 1m')
  })
  it('formats numbers and bytes', () => {
    expect(fmtNum(0.123456)).toBe('0.1235')
    expect(fmtNum(null)).toBe('—')
    expect(fmtBytes(2048)).toBe('2.0 KB')
  })
})
