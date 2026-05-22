# MDL 2차 프로젝트 폴더 구조

이 폴더는 1차 POC 산출물, 2차 실험 환경, 참고문서, 원천/샘플 데이터를 분리해서 찾기 쉽도록 정리한 구조입니다.

## 주요 위치

| 경로 | 용도 |
| --- | --- |
| `00_current_work/current_test_env/` | 2차 프로젝트에서 마지막으로 수행한 현재 테스트 환경 복사본 |
| `01_legacy_poc/master-document-list-project-main/` | 작년 1차 POC 개발 프로젝트 원본 |
| `02_experiments/prompt-test-history/` | 프롬프트 테스트 및 실험 스크립트 이력 복사본 |
| `03_reference_docs/proposals/` | 제안서 및 과제 범위 관련 문서 |
| `03_reference_docs/prompt_feedback/` | 두산 피드백 기반 프롬프트 문서 |
| `03_reference_docs/system_notes/` | 기존 시스템 구조/흐름 정리 문서 |
| `03_reference_docs/vendor_docs/` | 기타 제공 문서 및 도면 관련 참고자료 |
| `04_data/sample_documents/project_samples/` | 프로젝트별 샘플 ITB/MDL 문서 |
| `04_data/source_archives/SourceData/` | SourceData 원천 zip 모음 |
| `05_archives/` | 기존 zip 백업 및 압축본 |

## 정리 기준

- 1차 POC 코드는 컨셉 참고용으로만 보고 `01_legacy_poc/`에 격리합니다.
- 2차 개발의 기준점은 `00_current_work/current_test_env/`입니다.
- 데이터는 `04_data/`, 문서는 `03_reference_docs/`, 압축 백업은 `05_archives/`에 둡니다.
- 삭제는 하지 않았습니다. 이동이 막힌 폴더는 복사본을 만든 뒤 원본을 그대로 보존했습니다.

## 남아있는 예외

`prompt-test/` 원본 폴더는 파일 시스템 권한 문제로 이동되지 않았습니다. 동일한 내용은 `02_experiments/prompt-test-history/`와 `00_current_work/current_test_env/`에 복사되어 있으므로, 다음 작업은 복사된 새 위치를 기준으로 진행하면 됩니다.
