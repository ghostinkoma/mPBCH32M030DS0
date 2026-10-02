# ホストで動く単体テスト (実機不要):  make -C firmware/tests
CC ?= gcc
test: host_test test_stepper test_rgbw
	./host_test
	./test_stepper
	./test_rgbw
test_rgbw: test_rgbw.c ../lib/mpb_rgbw.c ../lib/mpb_rgbw.h stub/mpb.h
	$(CC) -O1 -Wall -Wno-unused-function -Istub -I../lib -o $@ test_rgbw.c
test_stepper: test_stepper.c ../lib/mpb_stepper.c ../lib/mpb_stepper.h stub/mpb.h
	$(CC) -O1 -Wall -Wno-unused-function -Istub -I../lib -o $@ test_stepper.c
host_test: host_test.c ../lib/mpb_log.c ../lib/mpb_env.c ../lib/mpb_cie.h stub/mpb.h
	$(CC) -O1 -Wall -Wno-unused-function -Istub -I../lib -o $@ host_test.c
clean:
	rm -f host_test test_stepper test_rgbw
.PHONY: test clean
